"""Holds the plans awaiting a human decision (PRD §14.2, §14.4).

An approval request is a piece of state with a lifetime: it is created when a
plan is ready, it expires if nobody looks at it, and it ends in a decision that
must be recorded. Keeping that in one place — rather than as a variable inside
whatever built the plan — is what lets the batch review queue exist at all.

In-memory for now. Persisting it belongs with the tracker in M10; the interface
here is deliberately the one a database-backed version would also offer.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from haru.adapters.plan import ApplicationPlan
from haru.brain.provenance import utcnow

#: Approval requests expire rather than sitting live forever (PRD §14.2).
DEFAULT_TTL = timedelta(hours=24)


class Decision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class PendingApproval:
    """One plan waiting for a person."""

    plan: ApplicationPlan
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=utcnow)
    ttl: timedelta = DEFAULT_TTL
    decision: Decision = Decision.PENDING
    decided_at: datetime | None = None
    note: str = ""

    @property
    def is_expired(self) -> bool:
        return utcnow() - self.created_at > self.ttl

    @property
    def status(self) -> Decision:
        if self.decision is Decision.PENDING and self.is_expired:
            return Decision.EXPIRED
        return self.decision

    @property
    def needs_attention(self) -> int:
        """How much of this one a human must handle. Drives queue ordering."""
        return len(self.plan.to_ask) + len(self.plan.blockers())

    @property
    def title(self) -> str:
        ask = self.plan.ask
        return f"{ask.role or 'Application'} — {ask.org or 'unknown company'}"


class ApprovalRegistry:
    """Thread-safe store of pending approvals."""

    def __init__(self) -> None:
        self._items: dict[str, PendingApproval] = {}
        self._lock = threading.Lock()

    def submit(self, plan: ApplicationPlan, *, ttl: timedelta = DEFAULT_TTL) -> PendingApproval:
        item = PendingApproval(plan=plan, ttl=ttl)
        with self._lock:
            self._items[item.id] = item
        return item

    def get(self, approval_id: str) -> PendingApproval | None:
        return self._items.get(approval_id)

    def pending(self) -> list[PendingApproval]:
        """Awaiting a decision, most demanding first.

        Sorted by how much human attention each needs, matching the batch
        review rule in PRD §14.4 — the routine tail sinks to the bottom where
        it can be handled together.
        """
        items = [i for i in self._items.values() if i.status is Decision.PENDING]
        return sorted(items, key=lambda i: (-i.needs_attention, i.created_at))

    def decided(self) -> list[PendingApproval]:
        return sorted(
            (i for i in self._items.values() if i.decision is not Decision.PENDING),
            key=lambda i: i.decided_at or i.created_at,
            reverse=True,
        )

    def approve(self, approval_id: str, *, note: str = "") -> PendingApproval:
        """Record approval. Refuses while the plan has blockers.

        The gate lives here rather than in the page so that every route — and
        any future chat surface — inherits it (PRD §14.1).
        """
        item = self._require(approval_id)
        if item.status is Decision.EXPIRED:
            raise ApprovalExpired(f"approval {approval_id} expired")
        blockers = item.plan.blockers()
        if blockers:
            raise NotSubmittable(blockers)
        with self._lock:
            item.decision = Decision.APPROVED
            item.decided_at = utcnow()
            item.note = note
        return item

    def reject(self, approval_id: str, *, note: str = "") -> PendingApproval:
        item = self._require(approval_id)
        with self._lock:
            item.decision = Decision.REJECTED
            item.decided_at = utcnow()
            item.note = note
        return item

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def _require(self, approval_id: str) -> PendingApproval:
        item = self._items.get(approval_id)
        if item is None:
            raise KeyError(approval_id)
        return item

    def __len__(self) -> int:
        return len(self._items)


class NotSubmittable(Exception):
    """Approval was attempted on a plan that is not ready."""

    def __init__(self, blockers: list[str]) -> None:
        self.blockers = blockers
        super().__init__("; ".join(blockers))


class ApprovalExpired(Exception):
    """The request sat unanswered past its lifetime."""
