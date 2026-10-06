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
from claytonlib.battle_compass.sim import (
    FLINCH_EFFECTS, HuntConfig, accuracy_net_stage, can_flinch, can_miss, effective_speed,
    simulate_turn, status_applied_by, will_fail,
)
from claytonlib.battle_compass.solver import Solution, SolverConfig, Unreachable, solve
from claytonlib.battle_compass.state import Action, Battler, Status
from claytonlib.moves import CATEGORY_STATUS, resolve_move

#: How many candidate rows a snapshot carries. The full set can be 1,200 wide; the UI shows the
#: nearest few and a count, and the window is sorted centre-first so these are the likeliest.
CANDIDATE_PREVIEW = 12


def _item_name(code: str) -> str:
    """An item code as its name, for plain-language rendering. Falls back to the code."""
    try:
        return f"a {items.item(code).name}"
    except ValueError:
        return code


def _party_namer(state):
    """A lookup from party slot to Pokemon name, for plain-language rendering.

    Built off the state being described rather than held on the session, so a history row
    replayed from before a switch names the Pokemon who was in that slot then -- which, because
    slots are stable, is the same Pokemon either way. That is the point of making them stable.
    """
    by_slot = {state.ours.party_slot or 1: state.ours.name}
    for i, b in enumerate(state.bench):
        by_slot.setdefault(b.party_slot or i + 2, b.name)
    return by_slot.get


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
                     special_attack=target.stats["spa"], types=target.types,
                     ability=target.ability, held_item=target.held_item),
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


def move_info(battler: Battler, defender: Battler | None = None) -> list[dict]:
    """Per slot: what the UI must know to ask the right questions about this move.

    A damaging move renders a hit marker (``h``/``!``); a status move that lands renders the bare
    slot, so asking "did it crit?" about Mean Look would be nonsense. Deriving this here rather
    than in the page keeps one source of truth for it.

    Two flags exist to stop the interview offering impossible outcomes:

    * ``can_miss`` -- only when an accuracy roll can actually fail. Accuracy 0 skips the check and
      accuracy 100 always passes it, so Spore, False Swipe and Sweet Scent cannot miss.
    * ``guaranteed_fail`` -- the move is certain to do nothing given `defender`'s state, and
      renders as the bare slot rather than as a miss. Spore against an already-paralyzed Suicune
      is the case: statuses are mutually exclusive, so it rolls accuracy and then fails.
    """
    out: list[dict] = []
    for slot in range(len(battler.moves)):
        move = battler.move(slot)
        if move is None:
            out.append({"slot": slot, "name": "", "known": False, "damaging": False,
                        "can_miss": False, "guaranteed_fail": False, "has_secondary": False,
                        "flinch_secondary": False, "applies_status": None,
                        "effect_chance": 0, "priority": 0, "pp": 0})
            continue
        out.append({
            "slot": slot,
            "name": move.name,
            "known": True,
            "damaging": move.category != CATEGORY_STATUS,
            # Stage-dependent: a 100%-accuracy move becomes missable under an accuracy drop or
            # a raised evasion, so this is computed against the real defender, not assumed.
            "can_miss": can_miss(move, accuracy_net_stage(battler, defender)
                                 if defender is not None else 0),
            "guaranteed_fail": defender is not None and will_fail(move, defender),
            # A secondary effect is observable ("Smeargle's Attack fell!") and renders its own
            # `~` token, so the interview has to ask about it or such a turn is unreportable.
            "has_secondary": move.effect_chance > 0,
            # ...with one exception, which is why this flag exists. A flinch is announced on the
            # VICTIM's turn, so a flinching move that goes SECOND leaves no trace at all: there
            # is nothing to ask and nothing to report. See `sim.flinch_visible`.
            "flinch_secondary": move.effect in FLINCH_EFFECTS,
            "effect_chance": move.effect_chance,
            # The non-volatile status this move inflicts, as its token marker, or None. The
            # interview needs it because a status WE apply lands before the target's turn: once
            # Spore connects, "is asleep" is the only thing the target can have done, and it was
            # not on offer because the snapshot's options are read off the turn's OPENING state.
            "applies_status": (st.value if (st := status_applied_by(move)) else None),
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
    #: Which party member came in after a faint. Not part of the action -- a faint is something
    #: the turn did to us -- but replay needs it just the same, since it decides who is out next.
    replacement: int | None = None

    @property
    def extra(self) -> dict:
        out = {}
        if self.item_code is not None:
            out["item_code"] = self.item_code
        if self.bench_slot is not None:
            out["bench_slot"] = self.bench_slot
        if self.replacement is not None:
            out["replacement"] = self.replacement
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
        # Party slots are assigned here when the caller did not set them, so every S/X/R token a
        # run emits names a STABLE position: the lead is slot 1 and the bench follows it in
        # order, exactly as the hunt configuration lists them. The app sets them explicitly from
        # `hunt.party` (which is more accurate, since a missing member leaves a gap); this is the
        # fallback that keeps a directly-constructed party sane.
        self.ours = ours if ours.party_slot else replace(ours, party_slot=1)
        self.bench = tuple(b if b.party_slot else replace(b, party_slot=i + 2)
                           for i, b in enumerate(bench))
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
        #: Why a forced Phase 2 could not produce a path, if it could not.
        self.forced_reason: str | None = None
        #: Each mid-run widening, so a run record says the window was not what it started as.
        self.widenings: list[dict] = []
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
                                    item_code=turn.item_code, bench_slot=turn.bench_slot,
                                    replacement=turn.replacement))
        self.turns = replayed
        # A transition recorded after the last surviving turn has not happened yet.
        self.transitions = [(at, p) for at, p in self.transitions if at <= len(replayed)]
        self._apply_transitions_at(len(replayed))

    def rebase(self, window: CandidateWindow) -> dict:
        """Swap in a wider candidate window and replay the run against it.

        Recovery for the case that matters: the reported turn matched nothing because the true
        seed was never in the window. Restarting would throw away every turn already reported,
        which is the expensive half of a run -- and those turns are exactly what filters the newly
        admitted candidates, so replaying them costs nothing in information.

        `window` must be a SUPERSET of the current one. A turn that was accepted once has to stay
        accepted, or the history becomes unexplainable and `_replay` would (correctly) refuse; and
        narrowing here would silently discard candidates the player never ruled out.
        """
        missing = {c.seed for c in self.window.candidates} - {c.seed for c in window.candidates}
        if missing:
            raise ValueError(
                f"a wider window must still contain the current candidates; {len(missing)} of "
                f"{len(self.window.candidates)} would be dropped. Widen the frame or second "
                f"range rather than moving the centre.")
        before = len(self.survivors)
        self.window = window
        self._replay(self.turns)
        self.widenings.append({
            "frame_window": window.frame_window,
            "second_window": window.second_window,
            "candidates": len(window.candidates),
            "survivors_before": before,
            "survivors_after": len(self.survivors),
            "after_turn": len(self.turns),
        })
        return self.snapshot()

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
        not a thing candidates can disagree about.

        Both balls are legal in every phase -- see `Phase`. A standard ball's danger is reported
        by `standard_ball_risk` rather than removed from the list, because the risk is small,
        quantified, and the player's to weigh; and the capture ball never carried one.

        ``REVIVE`` appears only while somebody is actually down to revive, and ``FAINTED`` only
        while the target could move before us -- otherwise we always got our move off, so being
        fainted before moving is not a thing that can have happened.
        """
        state = next(iter(self._session.states.values()))
        actions = [_MOVE_ACTIONS[slot] for slot in state.ours.usable_slots()]
        actions.extend([Action.ITEM, Action.ITEM_CURE])
        actions.extend([Action.CAPTURE_BALL, Action.STANDARD_BALL])
        if self.phase is Phase.SETUP and state.healthy_bench:
            actions.append(Action.SWITCH)
        if any(b.fainted for b in state.bench):
            actions.append(Action.REVIVE)
        if self.target_can_move_first():
            actions.append(Action.FAINTED)
        return actions

    def target_can_move_first(self) -> bool:
        """Whether the target could take its turn before ours, by Speed or by priority.

        The gate on reporting "fainted before moving": if we always move first, we always got the
        move off, and offering the option would invite a report no candidate can predict.

        Three ways it is true, which is how the feedback put it: the target outspeeds us, the
        target has a raised-priority move, or one of ours has a lowered-priority move. Checked
        against the moves both sides actually have rather than on Speed alone.
        """
        state = next(iter(self._session.states.values()))
        if effective_speed(state.target) > effective_speed(state.ours):
            return True
        theirs = [m.priority for slot in range(len(state.target.moves))
                  if (m := state.target.move(slot)) is not None]
        ours = [m.priority for slot in range(len(state.ours.moves))
                if (m := state.ours.move(slot)) is not None]
        return max(theirs, default=0) > min(ours, default=0)

    def predict(self, action: Action, **extra) -> dict[int, str]:
        return self._session.predict(action, **extra)

    def action_label(self, action: Action, item_code: str | None = None) -> str:
        """What the action is, in words. "Use False Swipe", not "M1".

        Built from the same move names the interview's chips use, because a ranking nobody can
        read is a ranking nobody acts on -- and worse than unread, a code the player has to
        translate under time pressure is a code they translate wrongly. "M1" and "M4" differ by
        one character and name two completely different moves.

        `item_code` names the actual item when there is one, so a solver step reads "Use a Hyper
        Potion" rather than the bare "Use an item" it would otherwise share with every other
        bag action in the path.
        """
        state = next(iter(self._session.states.values()))
        slot = action.move_slot
        if slot is not None:
            move = state.ours.move(slot)
            return f"Use {move.name}" if move else f"Use move {slot + 1}"
        if action in (Action.ITEM, Action.ITEM_CURE) and item_code:
            try:
                return f"Use a {items.item(item_code).name}"
            except ValueError:
                pass                      # an unknown code falls back to the generic wording
        return {
            Action.ITEM: "Use an item",
            Action.ITEM_CURE: "Use a status cure",
            Action.CAPTURE_BALL: f"Throw the {self.capture_ball or 'capture ball'}",
            Action.STANDARD_BALL: "Throw a Poke Ball",
            Action.SWITCH: "Switch Pokemon",
            Action.REVIVE: "Use a Revive",
            Action.FAINTED: "Fainted before moving",
        }.get(action, action.value)

    def standard_ball_risk(self) -> dict | None:
        """How dangerous it is to throw a plain Poke Ball right now.

        The fraction of surviving candidates on which a standard ball would **capture** -- which
        loses the run, because the target ends up in the wrong ball (sec 2.3). So this is a risk
        gauge, not a progress one: 0% means the throw is free information, and anything above that
        is the chance of throwing the hunt away.

        Reported in every phase, including Phase 1 and including a pinned seed. With one
        candidate it is no longer a percentage but a verdict -- 0% or 100%, "free information" or
        "this throw ends the run" -- which is the most actionable it ever gets, so suppressing it
        there would hide the answer exactly when it is certain.

        `matches_capture_ball` says whether the risk is the harsh kind. On Suicune both balls are
        a flat x1 so a landing is a lost run; where the capture ball actually matches, a standard
        ball is far weaker and a probe is cheap.

        None only when there are no candidates left to measure.
        """
        states = list(self._session.states.values())
        if not states:
            return None
        caught = 0
        for state in states:
            nxt = simulate_turn(state, Action.STANDARD_BALL, self.config)
            caught += bool(nxt.captured_in_wrong_ball)
        return {
            "candidates": len(states),
            "would_catch": caught,
            "percent": round(100.0 * caught / len(states), 1),
            "safe": caught == 0,
            "matches_capture_ball": self.config.standard_ball_matches_capture_ball(),
        }

    def advice(self) -> list[dict]:
        """Actions ranked by how much they would narrow the set, best first (Phase 1.5).

        Empty once the seed is pinned -- there is nothing left to learn, and Phase 2 optimises
        distance instead.
        """
        if self.identified is not None:
            return []
        # Only actions the player can CHOOSE. A Revive needs a target this does not know, and
        # being fainted before moving is not a choice at all -- ranking either would offer advice
        # nobody can act on.
        choosable = [a for a in self.legal_actions()
                     if a not in (Action.REVIVE, Action.FAINTED)]
        ranked = self._session.rank_actions(choosable)
        return [{"action": a.value, "label": self.action_label(a),
                 "expected_survivors": round(score, 2),
                 "groups": len(self._session.partition(a))} for a, score in ranked]

    # -- the loop -------------------------------------------------------

    def observe(self, action: Action, tokens: tuple[str, ...] | list[str],
                item_code: str | None = None, bench_slot: int | None = None,
                replacement: int | None = None) -> dict:
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
        if replacement is not None:
            extra["replacement"] = replacement
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
                                  item_code=item_code, bench_slot=bench_slot,
                                  replacement=replacement))
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

    def enter_solving(self, *, force: bool = False) -> dict:
        """Move to Phase 2 and solve.

        `force` proceeds despite `solver_blockers`. The blockers are what the SIMULATION believes,
        and it can be wrong in ways the player can see and it cannot -- an unmodelled damage
        modifier, say, leaves the simulated target above 1 HP when the real one is there. The
        player is looking at the game; refusing outright would make the tool unusable precisely
        when its model is the thing at fault. The caller is expected to confirm first.
        """
        if force:
            self._session.phase = Phase.SOLVING
        else:
            self._session.enter_solving()
        self.transitions.append((len(self.turns), Phase.SOLVING))
        try:
            self.solve()
        except ValueError as exc:
            # Forced past an unpinned seed: there is no single state to solve from. Say so
            # instead of failing the transition the player asked for.
            self.solution = None
            self.forced_reason = str(exc)
        return self.snapshot()

    def solve(self) -> Solution | Unreachable:
        """Re-solve from the current state. Called automatically every Phase 2 turn."""
        seed = self.identified
        if seed is None:
            raise ValueError("cannot solve until the seed is pinned")
        self.solution = solve(self._session.state_of(seed), self.config, self.solver_config)
        return self.solution

    # -- output ---------------------------------------------------------

    def run_record(self) -> dict:
        """This attempt as a saveable record (sec 15.4).

        Assembled here rather than in the page so the stored shape is decided by the thing that
        knows the run, not by whatever the UI happened to have in hand. Diagnostic only: nothing
        feeds it back into calibration.

        The two fields that make it worth keeping are `path` and `target_spread` -- together they
        are enough to replay the attempt. A record without the spread is unreproducible whenever
        Seed A was not the key seed, which is most runs.
        """
        return {
            "outcome": self.outcome(),
            "turns": len(self.turns),
            "path": tok.render_path([list(t.tokens) for t in self.turns]),
            "b_seed": self._candidate_row(self.identified) if self.identified else {},
            "items": self.items_spent(),
            "capture_ball": self.capture_ball,
            "window": {"frame_centre": self.window.frame_centre,
                       "second_centre": self.window.second_centre,
                       "frame_window": self.window.frame_window,
                       "second_window": self.window.second_window,
                       "size": len(self.window.candidates)},
            "widenings": list(self.widenings),
        }

    def outcome(self) -> str:
        """How the run ended, as one word -- or "" while it is still going.

        `all`, for the same reason the snapshot's flags use it: a candidate set that disagrees
        about whether the ball landed has not finished.
        """
        states = list(self._session.states.values())
        if not states:
            return ""
        if all(st.captured for st in states):
            return "caught"
        if all(st.captured_in_wrong_ball for st in states):
            return "wrong_ball"
        # The WIPE, not a faint: a faint with a replacement left is a turn, not an ending.
        if all(st.party_wiped for st in states):
            return "wiped"
        return ""

    def items_spent(self) -> dict[str, int]:
        """Items actually used, code -> count, from the reported turns.

        Read off the history rather than off the solver's plan: the plan is what was advised and
        the history is what happened, and the difference is exactly what a diagnostic record
        exists to show.
        """
        spent: dict[str, int] = {}
        for turn in self.turns:
            if turn.item_code:
                spent[turn.item_code] = spent.get(turn.item_code, 0) + 1
            elif turn.action is Action.REVIVE:
                # A Revive carries no item code -- it is its own action, with a party slot
                # instead -- but it is still something the run spent money on.
                spent["rev"] = spent.get("rev", 0) + 1
        return spent

    def explain(self, tokens) -> list[str]:
        """One turn's tokens as plain sentences, with this battle's names filled in.

        The grammar is dense on purpose and the interview exists so the player never types one --
        but tokens still surface where they have to be understood: the solver's recommended turn,
        the turns-so-far table, and a contradiction report. Same renderer for all three, so they
        cannot describe the same turn differently.

        Names come from the CURRENT active Pokemon, which is right for a recommendation and wrong
        for a history row played before a switch. `explain_history` handles that; this does not.
        """
        state = next(iter(self._session.states.values()))
        return tok.explain_turn(
            tokens, ours=state.ours.name, ours_moves=tuple(state.ours.moves),
            target=state.target.name, target_moves=tuple(state.target.moves),
            capture_ball=self.capture_ball or "capture ball",
            item_name=_item_name, party_name=_party_namer(state))

    def explain_history(self) -> list[list[str]]:
        """Every reported turn explained, one list of sentences per turn.

        Replayed from the window rather than read off the current state, because a turn played
        before a switch belongs to a different Pokemon with a different moveset -- naming its
        moves from whoever is out NOW would confidently describe the wrong move. This is the same
        hazard that keeps the turn table's action column in codes; replaying is what makes a
        plain-language version of it safe.
        """
        session = self._fresh()
        out: list[list[str]] = []
        for turn in self.turns:
            state = next(iter(session.states.values()))
            out.append(tok.explain_turn(
                turn.tokens, ours=state.ours.name, ours_moves=tuple(state.ours.moves),
                target=state.target.name, target_moves=tuple(state.target.moves),
                capture_ball=self.capture_ball or "capture ball", item_name=_item_name,
                party_name=_party_namer(state)))
            session.observe(turn.action, turn.tokens, **turn.extra)
        return out

    def _candidate_row(self, seed: int) -> dict:
        """One candidate as the page shows it: where it sits, and how far that is from the aim.

        The deltas are computed against the LIVE window centre rather than stored on the
        candidate, so a mid-run `rebase` cannot leave them describing a window that no longer
        exists.
        """
        info = self._session.candidate_info[seed]
        return {
            "seed": f"{seed:#010x}",
            "frame": info.frame,
            "second": info.second,
            "frame_delta": info.frame_delta(self.window.frame_centre),
            "second_delta": info.second_delta(self.window.second_centre),
        }

    def hp_range(self, side: str) -> dict:
        """(low, high) HP across every surviving candidate, for one side.

        The snapshot used to publish whichever candidate came first out of the dict, which showed
        one guess as though it were fact -- and candidates genuinely disagree, because they
        predict different damage rolls and different critical hits. A range says what is actually
        known: HP is at least `low`, at most `high`, and equal to one of them only once the seed
        is pinned.
        """
        values = [getattr(state, side).hp for state in self._session.states.values()]
        return {"low": min(values), "high": max(values), "certain": min(values) == max(values)}

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
        # How the run ENDED, which the snapshot never said. Its absence is why the capture bug
        # was reachable at all: with no terminal flag the page had no reason to stop asking for
        # turns, so the only thing between a landed ball and a fresh question was the solver
        # crashing. `all`, not `any`: a candidate set that disagrees about whether the ball
        # landed has not finished, and reporting a win on one member of it would be a lie.
        states = list(self._session.states.values())
        out = {
            "phase": int(self.phase),
            "phase_label": self.phase.label,
            "captured": all(st.captured for st in states),
            "captured_in_wrong_ball": all(st.captured_in_wrong_ball for st in states),
            # The run-ending kind: our Pokemon is down and there is nobody to replace it. A faint
            # with a replacement left is a reported TURN, not an ending, so this stayed false
            # through it -- which is the whole point of the distinction.
            "we_fainted": all(st.party_wiped for st in states),
            "party_wiped": all(st.party_wiped for st in states),
            # ...and this one says somebody went down *this* turn, replacement or not, so the
            # page can say so without claiming the run is over.
            "active_fainted": all(st.ours.fainted for st in states),
            "over": all(st.over for st in states),
            # Whether a plain Poke Ball is exactly as catchable as the capture ball here, which
            # is what decides how harshly to word a standard-ball throw. Replaces the old
            # `balls_allowed` flag: balls are always allowed now, so a key that was always true
            # told the page nothing, while this tells it which warning to show. Cheap -- config
            # arithmetic, not a candidate sweep, so it belongs on the snapshot where
            # `standard_ball_risk` does not.
            "standard_ball_matches_capture_ball":
                self.config.standard_ball_matches_capture_ball(),
            "survivors": len(self.survivors),
            "identified": None if seed is None else f"{seed:#010x}",
            "candidates": [self._candidate_row(s)
                           for s in self.survivors[:CANDIDATE_PREVIEW]],
            # Where the pinned seed actually landed, relative to where it was aimed. This is the
            # run's only feedback on its own timing: the seed alone says nothing about whether
            # the window was centred well, and the two axes miss near-independently, so a run
            # that was 30 frames late but dead-on the second is a different problem from one
            # that was a second out.
            "identified_at": None if seed is None else self._candidate_row(seed),
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
                     "hp_range": self.hp_range("ours"),
                     "ability": state.ours.ability,
                     "held_item": state.ours.held_item,
                     "effective_speed": effective_speed(state.ours),
                     "level": state.ours.level,
                     "types": list(state.ours.types),
                     "stats": dict(state.ours.stats),
                     "pp": [state.ours.pp_left(i) for i in range(len(state.ours.moves))],
                     "moves": list(state.ours.moves),
                     "move_info": move_info(state.ours, state.target)},
            "target": {"name": state.target.name, "hp": state.target.hp,
                       "max_hp": state.target.max_hp,
                       "status": state.target.status.value,
                       "confused": state.target.confused,
                       "hp_range": self.hp_range("target"),
                       "ability": state.target.ability,
                       "held_item": state.target.held_item,
                       "effective_speed": effective_speed(state.target),
                       "level": state.target.level,
                       "types": list(state.target.types),
                       # The full spread, for the popup that lets the player check it against the
                       # Pokemon once they have it. The run page shows HP and Speed inline, but
                       # the rest is only verifiable AFTER the catch -- so it is offered where
                       # that check happens rather than buried back in the search screen.
                       "stats": dict(state.target.stats),
                       "pp": [state.target.pp_left(i) for i in range(len(state.target.moves))],
                       "moves": list(state.target.moves),
                       "move_info": move_info(state.target, state.ours)},
            # `slot` is the BENCH index, which is what every call back into the session takes;
            # `party_slot` is the stable number the player sees in-game and the one the S/X/R
            # tokens name. Both, because they are not the same once anybody has switched.
            "bench": [{"slot": i, "name": b.name,
                       "party_slot": b.party_slot or i + 2,
                       "hp": b.hp, "max_hp": b.max_hp,
                       "fainted": b.fainted,
                       "status": b.status.value,
                       "moves": list(b.moves)}
                      for i, b in enumerate(state.bench)],
            "ours_party_slot": state.ours.party_slot or 1,
            # Whether "fainted before moving" is a reportable outcome at all.
            "target_can_move_first": self.target_can_move_first(),
            "revive_price": items.REVIVE_PRICE,
            "items": [{"code": i.code, "name": i.name, "price": i.price,
                       "heals": i.heals, "cures_status": i.cures_status,
                       "heal": i.heal}
                      for i in items.ITEMS],
            "capture_ball": self.capture_ball,
            "danger_floor": self.danger_floor,
            "in_danger": state.ours.hp is not None and state.ours.hp <= self.danger_floor,
            # The action column stays a CODE: `action_label` names a move from the currently
            # active Pokemon, so labelling a turn played before a switch would name the wrong
            # move, and the column pairs with `path` below, which is in codes anyway. `explain`
            # is the plain-language version and is safe because `explain_history` replays the
            # run, so each turn is described by whoever was actually out for it.
            "turns": [{"n": i + 1, "action": t.action.value, "rendered": t.rendered,
                       "explain": explanation,
                       "survivors_before": t.survivors_before,
                       "survivors_after": t.survivors_after}
                      for i, (t, explanation) in enumerate(
                          zip(self.turns, self.explain_history()))],
            "path": tok.render_path([list(t.tokens) for t in self.turns]),
            "legal_actions": [a.value for a in self.legal_actions()],
            "advice": self.advice() if include_advice else None,
            # True when advice exists to be fetched but was not computed here.
            "advice_pending": not include_advice and self.identified is None,
            "ambiguity": self._session.ambiguity(),
            "solver_blockers": self.solver_blockers(),
            "contradiction": self.contradiction,
            "forced_reason": self.forced_reason,
            "widenings": list(self.widenings),
            "solution": None,
        }
        if isinstance(self.solution, Solution):
            steps = self.solution.steps
            out["solution"] = {
                "found": True,
                # Zero steps is a real and good answer: the solver was asked for a path from a
                # state that is ALREADY captured, so the path is empty. `steps[0]` was taken
                # unconditionally, and the one turn a run exists to reach -- the capture landing
                # -- raised "list index out of range" the moment it was reported. The solver
                # re-runs after every Phase 2 turn, so the winning turn was guaranteed to hit it.
                "done": not steps,
                "turns": self.solution.turns,
                "distance": self.solution.total_distance,
                "rendered": self.solution.rendered(),
                "items": self.solution.item_bill(),
                "next": None if not steps else {
                    "action": steps[0].action.value,
                    "label": self.action_label(steps[0].action, steps[0].item),
                    "item": steps[0].item,
                    "expect": steps[0].rendered,
                    "explain": self.explain(steps[0].tokens)},
                "steps": [{"n": i + 1, "action": s.action.value,
                           "label": self.action_label(s.action, s.item), "item": s.item,
                           "expect": s.rendered, "distance": s.distance}
                          for i, s in enumerate(steps)],
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
