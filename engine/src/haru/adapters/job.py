"""Reading a job posting and judging fit (PRD §8.1).

Extraction reuses the entity detection built for the validator: the same
machinery that decides "is this a named technology?" when checking output works
for reading requirements out of a posting.

Fit scoring is deliberately blunt — coverage of the posting's requirements by
confirmed facts. It exists to answer one question honestly: *should you apply
to this at all?* A low score is reported as a low score rather than quietly
padded, because the alternative is Haru encouraging applications it knows are
weak (PRD §8.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from haru.brain.fact_boundary import FactBoundary
from haru.cv.models import Ask
from haru.validation.detect import (
    canonical,
    find_lowercase_tech,
    find_mentions,
    tokenize,
)
from haru.validation.lexicon import GENERIC_TECH, KNOWN_TECH, ROLE_WORDS

#: Known applicant tracking systems, recognised from the URL.
ATS_HOSTS: dict[str, str] = {
    "greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "myworkdayjobs.com": "Workday",
    "workday.com": "Workday",
    "ashbyhq.com": "Ashby",
    "smartrecruiters.com": "SmartRecruiters",
    "taleo.net": "Taleo",
    "bamboohr.com": "BambooHR",
    "workable.com": "Workable",
    "jobvite.com": "Jobvite",
}

_TITLE_LINE = re.compile(r"^\s*(?:role|position|job title)\s*[:\-]\s*(.+)$", re.I | re.M)
_ORG_LINE = re.compile(r"^\s*(?:company|organisation|organization|employer)\s*[:\-]\s*(.+)$", re.I | re.M)


def detect_ats(url: str) -> str | None:
    lowered = url.lower()
    return next((name for host, name in ATS_HOSTS.items() if host in lowered), None)


def extract_requirements(text: str) -> tuple[str, ...]:
    """Pull the technologies and named skills a posting asks for.

    Ordered by first appearance and de-duplicated — postings tend to lead with
    what matters most.
    """
    seen: dict[str, str] = {}

    for mention in find_mentions(text):
        key = mention.key
        if not key or key in seen:
            continue
        if key in GENERIC_TECH or key in ROLE_WORDS:
            continue
        if " " in mention.text:
            continue  # multi-word runs here are usually company or team names
        seen[key] = mention.text

    for mention in find_lowercase_tech(text, KNOWN_TECH):
        if mention.key not in seen:
            seen[mention.key] = mention.text

    # Entity detection skips sentence-initial capitalised words, since there
    # they usually mean grammar rather than a name. For *extraction* that costs
    # recall — "Kubernetes a plus." would be missed, silently inflating the fit
    # score and pushing the user toward a job they match less well than told.
    # Known technologies are therefore swept for regardless of position.
    for token in tokenize(text):
        key = canonical(token)
        if key in KNOWN_TECH and key not in seen:
            seen[key] = token

    return tuple(seen.values())


def extract_ask(text: str, *, url: str = "", title: str = "") -> Ask:
    """Turn a posting into the :class:`Ask` the CV engine consumes."""
    role = None
    match = _TITLE_LINE.search(text)
    if match:
        role = match.group(1).strip()
    elif title:
        role = title.split("|")[0].split(" at ")[0].strip() or None

    org = None
    match = _ORG_LINE.search(text)
    if match:
        org = match.group(1).strip()
    elif " at " in title:
        org = title.split(" at ", 1)[1].split("|")[0].strip() or None

    return Ask(
        role=role,
        org=org,
        requirements=extract_requirements(text),
        raw_text=text,
    )


@dataclass(frozen=True)
class Fit:
    """How well the user matches a posting."""

    score: float
    matched: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def out_of_ten(self) -> int:
        return round(self.score * 10)

    @property
    def verdict(self) -> str:
        if self.score >= 0.7:
            return "strong match"
        if self.score >= 0.4:
            return "partial match"
        if self.score > 0:
            return "weak match"
        return "no overlap"

    def summary(self) -> str:
        line = f"{self.out_of_ten}/10 — {self.verdict}"
        if self.missing:
            line += f". Not on file: {', '.join(self.missing)}"
        return line


def score_fit(ask: Ask, boundary: FactBoundary) -> Fit:
    """Coverage of the posting's requirements by confirmed facts."""
    if ask.is_empty:
        return Fit(score=0.0, matched=(), missing=())

    matched: list[str] = []
    missing: list[str] = []
    for requirement in ask.requirements:
        key = canonical(requirement)
        if key in boundary.allowed_skills or key in boundary.preserved_projects:
            matched.append(requirement)
        else:
            missing.append(requirement)

    return Fit(
        score=len(matched) / len(ask.requirements),
        matched=tuple(matched),
        missing=tuple(missing),
    )
