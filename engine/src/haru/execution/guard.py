"""Guards that stop a loop becoming a runaway (PRD §12.6).

Three independent limits, because they fail differently:

* **Loop guard** — the model keeps asking for the same action. NaviNate's
  approach: signature on the element's *stable key*, nudge the model forward a
  few times, only then give up. An immediate abort is wrong, because one repeat
  is often just a slow page.
* **Step cap** — the model keeps doing *different* useless things. The loop
  guard never fires; only a total budget stops it.
* **Kill switch** — the user wants it to stop now. Checked before every action,
  and always available (PRD §12.6).
"""

from __future__ import annotations

import threading
from collections import Counter
from enum import Enum

from pydantic import BaseModel, ConfigDict


class StopReason(str, Enum):
    """Why the loop ended."""

    COMPLETED = "completed"
    STEP_CAP = "step_cap"
    REPEATED = "repeated"
    KILLED = "killed"
    BLOCKED = "blocked"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"


DEFAULT_STEP_CAP = 40
DEFAULT_REPEAT_LIMIT = 3


class KillSwitch:
    """Thread-safe stop flag. The user can always halt the agent."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def stop(self) -> None:
        self._event.set()

    def reset(self) -> None:
        self._event.clear()

    @property
    def stopped(self) -> bool:
        return self._event.is_set()


class LoopGuard(BaseModel):
    """Detects the model asking for the same thing over and over."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    repeat_limit: int = DEFAULT_REPEAT_LIMIT
    seen: Counter = None  # type: ignore[assignment]

    def model_post_init(self, _context) -> None:
        if self.seen is None:
            self.seen = Counter()

    def record(self, signature: str) -> int:
        """Register an attempt, returning how many times it has now been seen."""
        self.seen[signature] += 1
        return self.seen[signature]

    def is_repeat(self, signature: str) -> bool:
        return self.seen[signature] > 0

    def should_stop(self, signature: str) -> bool:
        return self.seen[signature] >= self.repeat_limit

    def nudge_for(self, signature: str) -> str:
        """Message fed back to the decider instead of re-running the action."""
        count = self.seen[signature]
        return (
            f"That action has already been performed {count}× and the page did "
            f"not change. Do something different, or finish the task."
        )

    def reset(self) -> None:
        self.seen.clear()


class StepBudget(BaseModel):
    """Total actions allowed for one goal."""

    cap: int = DEFAULT_STEP_CAP
    used: int = 0

    def spend(self) -> None:
        self.used += 1

    @property
    def exhausted(self) -> bool:
        return self.used >= self.cap

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.used)
