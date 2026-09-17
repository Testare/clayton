"""metronome_session.py — drive the interactive Seed B narrowing from the UI.

``narrow_candidates()`` is written for a console: ask a question, block on ``input()``,
narrow, repeat. To answer it one question at a time from an async UI, we run it on a
background thread whose input callback blocks on a queue. The facade hands the UI each
question (the input prompt plus whatever was printed since the last question); the UI
posts an answer, which unblocks the thread for the next question. When the driver
returns, the session carries the identified seed (or ``None``).

The UI never sees threads or queues — only ``{prompt, output, done, result}`` snapshots.
"""
from __future__ import annotations

import queue
import threading
import uuid

_ABORT = object()  # placed on the answer queue to make the driver abort


class SeedBSession:
    """One background narrowing run, answered one question at a time."""

    def __init__(self, runner):
        # runner(input_fn, output_fn) -> the identified candidate dict, or None.
        self.id = uuid.uuid4().hex[:12]
        self._questions: queue.Queue = queue.Queue()  # thread -> caller (prompt str, or _DONE)
        self._answers: queue.Queue = queue.Queue()    # caller -> thread (answer str, or _ABORT)
        self._out: list[str] = []
        self._out_lock = threading.Lock()
        self.done = False
        self.result = None
        self.error: str | None = None
        self._runner = runner
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # -- callbacks handed to narrow_candidates ---------------------------

    def _input_fn(self, prompt: str = "") -> str:
        self._questions.put(str(prompt))
        ans = self._answers.get()
        # Aborting reuses narrow_candidates' own "ABORT" keyword path, which returns
        # None cleanly and restores builtins.input.
        return "ABORT" if ans is _ABORT else ans

    def _output_fn(self, *args) -> None:
        with self._out_lock:
            self._out.append(" ".join(str(a) for a in args))

    def _run(self) -> None:
        try:
            self.result = self._runner(self._input_fn, self._output_fn)
        except Exception as e:  # surface to the caller rather than dying silently
            self.error = repr(e)
        finally:
            self.done = True
            self._questions.put(_DONE)

    # -- snapshots --------------------------------------------------------

    def _drain_output(self) -> list[str]:
        with self._out_lock:
            lines, self._out = self._out, []
        return lines

    def _next_state(self, timeout: float = 30.0) -> dict:
        item = self._questions.get(timeout=timeout)
        output = self._drain_output()
        if item is _DONE:
            return {"session_id": self.id, "done": True, "output": output,
                    "result": self.result, "error": self.error}
        return {"session_id": self.id, "done": False, "prompt": item, "output": output}

    def answer(self, text) -> dict:
        if self.done:
            return {"session_id": self.id, "done": True, "output": [],
                    "result": self.result, "error": self.error}
        self._answers.put(str(text))
        return self._next_state()

    def abort(self) -> dict:
        if not self.done:
            self._answers.put(_ABORT)
            self._next_state()  # let the thread unwind
        return {"session_id": self.id, "done": True, "result": None, "aborted": True}


_DONE = object()


class SessionRegistry:
    """Tracks live narrowing sessions by id (one per in-progress Seed B run)."""

    def __init__(self):
        self._sessions: dict[str, SeedBSession] = {}

    def start(self, runner) -> tuple[str, dict]:
        s = SeedBSession(runner)
        self._sessions[s.id] = s
        state = s._next_state()  # first question, or immediate completion
        if state.get("done"):
            self._sessions.pop(s.id, None)
        return s.id, state

    def answer(self, session_id: str, text) -> dict:
        s = self._sessions.get(session_id)
        if s is None:
            raise ValueError(f"unknown or finished session {session_id!r}")
        state = s.answer(text)
        if state.get("done"):
            self._sessions.pop(session_id, None)
        return state

    def abort(self, session_id: str) -> dict:
        s = self._sessions.pop(session_id, None)
        if s is None:
            return {"session_id": session_id, "done": True, "aborted": True}
        return s.abort()
