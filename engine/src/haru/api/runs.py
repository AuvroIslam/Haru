"""Live view of a running agent (PRD §4.17 — the activity timeline).

Watching each field get filled *and verified* is the most trust-building thing
this product can show. The loop already produces a
:class:`~haru.execution.loop.Step` per turn, so a run only needs somewhere to
collect them and a way to notice new ones.

Deliberately no WebSocket: server-sent events are one-directional, which is all
this needs, and they survive a reconnect without any client library. The whole
client is a dozen lines of inline JavaScript.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from haru.brain.provenance import utcnow
from haru.execution.guard import StopReason
from haru.execution.loop import Step


@dataclass
class RunRecord:
    """One agent run and everything it has done so far."""

    title: str
    url: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    reason: StopReason | None = None
    steps: list[Step] = field(default_factory=list)
    _event: threading.Event = field(default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ── writing ──────────────────────────────────────────────────────────

    def record(self, step: Step) -> None:
        with self._lock:
            self.steps.append(step)
        self._wake()

    def finish(self, reason: StopReason) -> None:
        with self._lock:
            self.reason = reason
            self.finished_at = utcnow()
        self._wake()

    def _wake(self) -> None:
        """Release anyone waiting, then re-arm for the next change."""
        self._event.set()
        self._event.clear()

    # ── reading ──────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self.finished_at is None

    @property
    def verified_count(self) -> int:
        return sum(1 for s in self.steps if s.verified)

    @property
    def has_problems(self) -> bool:
        return any(not s.verified or not s.performed for s in self.steps)

    def wait_for_change(self, timeout: float = 15.0) -> bool:
        """Block until something happens, or the timeout expires."""
        return self._event.wait(timeout)

    def as_events(self, since: int = 0) -> list[dict]:
        """Steps after ``since``, shaped for the browser."""
        with self._lock:
            tail = self.steps[since:]
            offset = since
        return [
            {
                "index": offset + i,
                "action": step.action.describe(),
                "reason": step.action.reason,
                "performed": step.performed,
                "verified": step.verified,
                "note": step.note,
            }
            for i, step in enumerate(tail)
        ]

    def summary(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "running": self.is_running,
            "reason": self.reason.value if self.reason else None,
            "steps": len(self.steps),
            "verified": self.verified_count,
        }


class RunManager:
    """Holds runs so the UI can watch them."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.Lock()

    def start(self, title: str, *, url: str = "") -> RunRecord:
        run = RunRecord(title=title, url=url)
        with self._lock:
            self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def active(self) -> list[RunRecord]:
        return [r for r in self._runs.values() if r.is_running]

    def recent(self, limit: int = 10) -> list[RunRecord]:
        return sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)[:limit]

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()

    def __len__(self) -> int:
        return len(self._runs)


def sse(event: str, payload: dict) -> str:
    """Format one server-sent event."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def stream(run: RunRecord, *, heartbeat: float = 15.0):
    """Yield SSE frames for a run until it finishes.

    A heartbeat keeps proxies and idle sockets from dropping a run that is
    thinking rather than acting.
    """
    sent = 0
    yield sse("summary", run.summary())
    for event in run.as_events():
        yield sse("step", event)
        sent += 1

    while run.is_running:
        run.wait_for_change(heartbeat)
        for event in run.as_events(since=sent):
            yield sse("step", event)
            sent += 1
        if not run.is_running:
            break
        yield ": keep-alive\n\n"

    for event in run.as_events(since=sent):
        yield sse("step", event)
        sent += 1
    yield sse("done", run.summary())
