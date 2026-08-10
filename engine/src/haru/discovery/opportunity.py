"""Opportunities captured from anywhere (PRD §9).

The design decision this module encodes: Haru does **not** log into Facebook or
LinkedIn and scrape a feed. That is the behaviour that got AIHawk detected and
abandoned, and the penalty lands on the user as a suspended account on their
real professional network.

Instead the user is already looking at the post, and capture reads the page
they are on. It costs nothing in risk and reaches the long tail no scraper
touches — Discord servers, private groups, newsletters, a friend's message.

Classification is signal-based rather than model-based where it can be: a
Greenhouse URL is a job posting with certainty, and spending a model call to
rediscover that would be silly.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from haru.brain.models import _new_id
from haru.brain.provenance import today as local_today, utcnow


class Kind(str, Enum):
    JOB = "job"
    HACKATHON = "hackathon"
    GRANT = "grant"
    PROGRAM = "program"
    GOVERNMENT_FORM = "government_form"
    UNKNOWN = "unknown"


class Source(str, Enum):
    """How it reached the inbox. All are passive — none scrape a feed."""

    BROWSER_CAPTURE = "browser_capture"
    FORWARDED = "forwarded"
    EMAIL_INGEST = "email_ingest"
    WEB_SEARCH = "web_search"
    FEED = "feed"
    WATCHED_PAGE = "watched_page"
    MANUAL = "manual"


class Status(str, Enum):
    CAPTURED = "captured"
    ENRICHED = "enriched"
    SCORED = "scored"
    QUEUED = "queued"
    DISMISSED = "dismissed"
    APPLIED = "applied"
    EXPIRED = "expired"


#: Hosts that identify a kind with certainty. No model call needed.
HOST_SIGNALS: dict[str, Kind] = {
    "greenhouse.io": Kind.JOB,
    "lever.co": Kind.JOB,
    "myworkdayjobs.com": Kind.JOB,
    "ashbyhq.com": Kind.JOB,
    "smartrecruiters.com": Kind.JOB,
    "workable.com": Kind.JOB,
    "bamboohr.com": Kind.JOB,
    "linkedin.com/jobs": Kind.JOB,
    "indeed.com": Kind.JOB,
    "devpost.com": Kind.HACKATHON,
    "devfolio.co": Kind.HACKATHON,
    "dorahacks.io": Kind.HACKATHON,
    "mlh.io": Kind.HACKATHON,
    "hackerearth.com": Kind.HACKATHON,
    "grants.gov": Kind.GRANT,
    "gov.uk": Kind.GOVERNMENT_FORM,
    ".gov/": Kind.GOVERNMENT_FORM,
}

_KEYWORDS: dict[Kind, tuple[str, ...]] = {
    Kind.HACKATHON: ("hackathon", "hack the", "devpost", "submission deadline",
                     "prize track", "demo day", "judging criteria"),
    Kind.JOB: ("apply now", "job description", "we are hiring", "responsibilities",
               "qualifications", "full-time", "salary", "benefits package"),
    Kind.GRANT: ("grant", "funding round", "eligibility criteria", "award amount",
                 "proposal deadline"),
    Kind.PROGRAM: ("fellowship", "cohort", "accelerator", "residency", "scholarship"),
    Kind.GOVERNMENT_FORM: ("visa", "passport", "immigration", "tax return",
                           "benefit claim", "application form", "official use only"),
}

_DATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(
        r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\b",
        re.I,
    ),
    re.compile(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b",
        re.I,
    ),
)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
)}

_DEADLINE_CUE = re.compile(
    r"(deadline|closes?|due|apply by|submit by|closing date|last date)", re.I
)


class Opportunity(BaseModel):
    """Something the user might apply to."""

    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=_new_id)
    url: str = ""
    title: str = ""
    org: str = ""
    kind: Kind = Kind.UNKNOWN
    source: Source = Source.MANUAL
    status: Status = Status.CAPTURED
    text: str = ""
    deadline: date | None = None
    fit_score: float | None = None
    missing: tuple[str, ...] = ()
    captured_at: datetime = Field(default_factory=utcnow)
    note: str = ""

    @property
    def is_expired(self) -> bool:
        return self.deadline is not None and self.deadline < local_today()

    @property
    def days_left(self) -> int | None:
        if self.deadline is None:
            return None
        return (self.deadline - local_today()).days

    @property
    def is_urgent(self) -> bool:
        left = self.days_left
        return left is not None and 0 <= left <= 3

    def summary(self) -> str:
        parts = [self.title or self.url or "untitled"]
        if self.org:
            parts.append(self.org)
        parts.append(self.kind.value)
        if self.fit_score is not None:
            parts.append(f"{round(self.fit_score * 10)}/10")
        if self.deadline:
            left = self.days_left
            parts.append("expired" if left is not None and left < 0 else f"{left}d left")
        return " · ".join(parts)


def classify(url: str = "", text: str = "", title: str = "") -> Kind:
    """Work out what kind of thing this is.

    Host signals win outright — a Devpost URL is a hackathon regardless of what
    the page prose says. Keywords only decide when the host is unknown.
    """
    lowered_url = url.lower()
    for host, kind in HOST_SIGNALS.items():
        if host in lowered_url:
            return kind

    haystack = f"{title}\n{text}".lower()
    scores = {
        kind: sum(1 for word in words if word in haystack)
        for kind, words in _KEYWORDS.items()
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else Kind.UNKNOWN


def extract_deadline(text: str, *, today: date | None = None) -> date | None:
    """Find a submission deadline.

    Only dates near a deadline cue are used. A posting is full of dates — the
    company's founding year, a start date — and treating any of them as the
    deadline would put a wrong reminder in the user's calendar.
    """
    reference = today or local_today()

    relative = re.search(r"(\d+)\s+days?\s+(?:left|remaining|to go)", text, re.I)
    if relative:
        return reference + timedelta(days=int(relative.group(1)))

    for match in _DEADLINE_CUE.finditer(text):
        window = text[match.start() : match.start() + 120]
        found = _first_date(window)
        if found:
            return found
    return None


def _first_date(window: str) -> date | None:
    for pattern in _DATE_PATTERNS:
        match = pattern.search(window)
        if not match:
            continue
        try:
            groups = match.groups()
            if pattern is _DATE_PATTERNS[0]:
                return date(int(groups[0]), int(groups[1]), int(groups[2]))
            if pattern is _DATE_PATTERNS[1]:
                return date(int(groups[2]), _MONTHS[groups[1][:3].lower()], int(groups[0]))
            return date(int(groups[2]), _MONTHS[groups[0][:3].lower()], int(groups[1]))
        except (ValueError, KeyError):
            continue
    return None


def extract_json_ld(html: str) -> dict:
    """Read schema.org metadata if the page provides it.

    First of the three enrichment tiers (PRD §9.3): structured data is exact
    and free, so it is tried before selectors and long before a model.
    """
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    ):
        try:
            payload = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        for candidate in payload if isinstance(payload, list) else [payload]:
            if isinstance(candidate, dict) and "JobPosting" in str(candidate.get("@type", "")):
                return candidate
    return {}


def from_json_ld(data: dict) -> dict:
    """Map schema.org JobPosting fields onto our own."""
    if not data:
        return {}
    org = data.get("hiringOrganization") or {}
    result = {
        "title": data.get("title", ""),
        "org": org.get("name", "") if isinstance(org, dict) else str(org),
        "text": re.sub(r"<[^>]+>", " ", data.get("description", "")),
    }
    valid_through = data.get("validThrough")
    if isinstance(valid_through, str):
        try:
            result["deadline"] = datetime.fromisoformat(
                valid_through.replace("Z", "+00:00")
            ).date()
        except ValueError:
            pass
    return {k: v for k, v in result.items() if v}
