"""Live Battle Compass runs, keyed by id.

Deliberately *not* modelled on ``metronome_session.SeedBSession``. That class runs a generator on
a background thread whose input callback blocks on a queue, which is the right shape for a linear
interview: ask, wait, ask. Battle Compass is not one. It has phase transitions, it has undo, and
``battle_compass.identify.Session`` is already an explicit state machine -- so there is no
generator to drive, and a blocked thread cannot be rewound. This registry is therefore plain
synchronous storage, and undo works by replaying the observation history (sec 15.4.2).

Mid-battle state is intentionally in memory only, matching how Hunt documents its own scope: a
Hunt persists configuration, a finished attempt is saved as a run record, and the live encounter
in between is not persisted.
"""
from __future__ import annotations

import uuid


class HuntSessionRegistry:
    """Open runs by id. One per in-progress encounter."""

    def __init__(self):
        self._sessions: dict[str, tuple[str, object]] = {}

    def add(self, hunt_id: str, session) -> str:
        session_id = uuid.uuid4().hex[:12]
        self._sessions[session_id] = (hunt_id, session)
        return session_id

    def get(self, session_id: str):
        entry = self._sessions.get(session_id)
        if entry is None:
            raise ValueError(
                f"unknown or closed Battle Compass session {session_id!r}. Live runs are held in "
                f"memory only, so restarting the app ends them -- start a new run.")
        return entry[1]

    def hunt_of(self, session_id: str) -> str:
        entry = self._sessions.get(session_id)
        return entry[0] if entry else ""

    def for_hunt(self, hunt_id: str) -> list[str]:
        return [sid for sid, (hid, _) in self._sessions.items() if hid == hunt_id]

    def drop(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def __len__(self) -> int:
        return len(self._sessions)
