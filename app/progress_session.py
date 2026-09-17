"""progress_session.py — run a long computation on a background thread, polled for progress.

Unlike ``metronome_session`` (which pauses for an answer at each step), this is for work that
just runs to completion while periodically reporting how far it's gotten — a canon-map
precompute here. The runner gets a plain callback to call with whatever progress shape makes
sense for it; the caller polls a JSON snapshot until ``done``.

There is no cooperative cancellation: once started, the underlying compute (``precompute_canon``)
has no cancel hook, so "stopping" only stops the UI from watching it — the thread runs to
completion in the background regardless. Documented, not hidden, so a future precompute-side
cancel point isn't papered over by a fake button.
"""
from __future__ import annotations

import threading
import uuid


class ProgressSession:
    """One background run, polled for its latest progress snapshot."""

    def __init__(self, runner):
        # runner(progress_cb) -> JSON-able result. progress_cb(**fields) records a snapshot.
        self.id = uuid.uuid4().hex[:12]
        self._lock = threading.Lock()
        self._progress: dict = {}
        self.done = False
        self.result = None
        self.error: str | None = None
        self._thread = threading.Thread(target=self._run, args=(runner,), daemon=True)
        self._thread.start()

    def _progress_cb(self, **fields) -> None:
        with self._lock:
            self._progress = fields

    def _run(self, runner) -> None:
        try:
            self.result = runner(self._progress_cb)
        except Exception as e:  # surfaced to the caller, never silently dropped
            self.error = repr(e)
        finally:
            self.done = True

    def poll(self) -> dict:
        with self._lock:
            progress = dict(self._progress)
        return {
            "session_id": self.id, "done": self.done, "error": self.error,
            "progress": progress, "result": self.result if self.done else None,
        }


class ProgressRegistry:
    """Tracks live progress sessions by id."""

    def __init__(self):
        self._sessions: dict[str, ProgressSession] = {}

    def start(self, runner) -> dict:
        s = ProgressSession(runner)
        self._sessions[s.id] = s
        return s.poll()

    def poll(self, session_id: str) -> dict:
        s = self._sessions.get(session_id)
        if s is None:
            raise ValueError(f"unknown or forgotten session {session_id!r}")
        state = s.poll()
        if state["done"]:
            self._sessions.pop(session_id, None)
        return state
