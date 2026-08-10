"""The Opportunity Inbox (PRD §9.3).

    Captured → Classified → Enriched → Scored → Deduplicated → Queued

**Discovery never submits.** It fills a queue; a human decides what to act on.
That is not a limitation to be engineered away later — it is the difference
between a tool that finds things for you and one that applies on your behalf
without asking.

Duplicate detection matters more than it sounds. Applying twice to the same
role is embarrassing in a way that costs the user credibility, and the same
posting genuinely does arrive from three sources — a board, a newsletter, and a
friend — within a week.
"""

from __future__ import annotations

import re
import threading
from urllib.parse import urlparse, urlunparse

from haru.brain.fact_boundary import FactBoundary
from haru.cv.models import Ask
from haru.discovery.opportunity import (
    Kind,
    Opportunity,
    Source,
    Status,
    classify,
    extract_deadline,
    extract_json_ld,
    from_json_ld,
)

#: Query parameters that identify a campaign rather than a posting.
_TRACKING = re.compile(
    r"^(utm_|ref$|referrer$|source$|gclid$|fbclid$|mc_cid$|mc_eid$|trk$|trackingId$)",
    re.I,
)


def canonical_url(url: str) -> str:
    """Strip tracking parameters and normalise, so the same posting matches.

    The identical job arrives as ``…/jobs/1?utm_source=newsletter`` and
    ``…/jobs/1`` and must be recognised as one thing.
    """
    if not url:
        return ""
    parsed = urlparse(url.strip())
    kept = [
        part
        for part in parsed.query.split("&")
        if part and not _TRACKING.match(part.split("=")[0])
    ]
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", "&".join(sorted(kept)), ""))


def _identity(opportunity: Opportunity) -> tuple[str, str]:
    """Fallback identity when URLs differ: the role at the organisation."""
    return (
        re.sub(r"[^a-z0-9]+", "", opportunity.title.lower()),
        re.sub(r"[^a-z0-9]+", "", opportunity.org.lower()),
    )


class Inbox:
    """Everything captured, in one place."""

    def __init__(self) -> None:
        self._items: dict[str, Opportunity] = {}
        self._lock = threading.Lock()

    # ── capture ──────────────────────────────────────────────────────────

    def capture(
        self,
        *,
        url: str = "",
        text: str = "",
        title: str = "",
        html: str = "",
        org: str = "",
        source: Source = Source.BROWSER_CAPTURE,
        note: str = "",
    ) -> Opportunity:
        """Take in something the user is looking at, and work out what it is."""
        enriched = from_json_ld(extract_json_ld(html)) if html else {}

        opportunity = Opportunity(
            url=url,
            title=enriched.get("title") or title,
            org=enriched.get("org") or org,
            text=enriched.get("text") or text,
            source=source,
            note=note,
        )
        opportunity.kind = classify(url=url, text=opportunity.text, title=opportunity.title)
        opportunity.deadline = enriched.get("deadline") or extract_deadline(
            f"{opportunity.title}\n{opportunity.text}"
        )
        opportunity.status = Status.ENRICHED if enriched else Status.CAPTURED

        existing = self.find_duplicate(opportunity)
        if existing is not None:
            return self._merge(existing, opportunity)

        with self._lock:
            self._items[opportunity.id] = opportunity
        return opportunity

    def _merge(self, existing: Opportunity, incoming: Opportunity) -> Opportunity:
        """Keep the richer of two sightings rather than storing both."""
        with self._lock:
            if len(incoming.text) > len(existing.text):
                existing.text = incoming.text
            existing.title = existing.title or incoming.title
            existing.org = existing.org or incoming.org
            existing.deadline = existing.deadline or incoming.deadline
            if existing.kind is Kind.UNKNOWN:
                existing.kind = incoming.kind
        return existing

    # ── deduplication ────────────────────────────────────────────────────

    def find_duplicate(self, candidate: Opportunity) -> Opportunity | None:
        target_url = canonical_url(candidate.url)
        target_identity = _identity(candidate)

        for existing in self._items.values():
            if target_url and canonical_url(existing.url) == target_url:
                return existing
            if all(target_identity) and _identity(existing) == target_identity:
                return existing
        return None

    # ── scoring ──────────────────────────────────────────────────────────

    def score_all(self, boundary: FactBoundary) -> None:
        """Rate everything unscored against what the user can actually claim."""
        from haru.adapters.job import extract_ask, score_fit

        for opportunity in list(self._items.values()):
            if opportunity.fit_score is not None or not opportunity.text:
                continue
            ask: Ask = extract_ask(opportunity.text, title=opportunity.title)
            fit = score_fit(ask, boundary)
            with self._lock:
                opportunity.fit_score = fit.score
                opportunity.missing = fit.missing
                opportunity.status = Status.SCORED

    # ── reading ──────────────────────────────────────────────────────────

    def get(self, opportunity_id: str) -> Opportunity | None:
        return self._items.get(opportunity_id)

    def all(self) -> list[Opportunity]:
        return list(self._items.values())

    def queue(
        self,
        *,
        kind: Kind | None = None,
        min_fit: float | None = None,
        include_expired: bool = False,
    ) -> list[Opportunity]:
        """What is worth looking at, most pressing first.

        Ordering is urgency then fit: a deadline in two days matters more than
        a slightly better match with a month to run.
        """
        items = [
            o
            for o in self._items.values()
            if o.status not in (Status.DISMISSED, Status.APPLIED)
            and (include_expired or not o.is_expired)
            and (kind is None or o.kind is kind)
            and (min_fit is None or (o.fit_score or 0) >= min_fit)
        ]
        return sorted(
            items,
            key=lambda o: (
                0 if o.is_urgent else 1,
                o.days_left if o.days_left is not None else 9999,
                -(o.fit_score or 0),
            ),
        )

    def expiring(self) -> list[Opportunity]:
        return [o for o in self.queue() if o.is_urgent]

    def dismiss(self, opportunity_id: str, note: str = "") -> bool:
        item = self._items.get(opportunity_id)
        if item is None:
            return False
        with self._lock:
            item.status = Status.DISMISSED
            item.note = note or item.note
        return True

    def mark_applied(self, opportunity_id: str) -> bool:
        item = self._items.get(opportunity_id)
        if item is None:
            return False
        with self._lock:
            item.status = Status.APPLIED
        return True

    def already_applied(self, url: str) -> bool:
        """Guard against applying to the same posting twice."""
        target = canonical_url(url)
        return any(
            o.status is Status.APPLIED and canonical_url(o.url) == target
            for o in self._items.values()
        )

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for opportunity in self._items.values():
            result[opportunity.kind.value] = result.get(opportunity.kind.value, 0) + 1
        return result

    def __len__(self) -> int:
        return len(self._items)
