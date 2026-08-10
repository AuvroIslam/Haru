"""The fact boundary: the set of things that may truthfully be claimed.

PRD §10.2. This module builds the boundary; the validator that enforces it
lands in M3. Keeping the two apart matters — the boundary is derived purely
from stored, confirmed facts, so it cannot be widened by anything a language
model produces.

Four rules are enforced here rather than left to the validator, because they
are properties of the data and would otherwise be restated (and eventually
mis-stated) at every call site:

1. Only **confirmed** records contribute (PRD §6.3).
2. A skill contributes only if it has **evidence** linking it to real work.
3. A credential contributes only if it is confirmed **and** has a supporting
   document — certifications are never stretchable.
4. A metric may be cited only if it is marked **verified**.

``never_claim`` is user-set and always wins.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable

from pydantic import BaseModel, ConfigDict, Field

from haru.brain.models import (
    DEFAULT_PROFILE_ID,
    Credential,
    Education,
    Experience,
    Project,
    Skill,
)

if TYPE_CHECKING:
    from haru.brain.store import BrainStore

_NOISE = re.compile(r"[^a-z0-9+#]+")


def normalize(term: str) -> str:
    """Fold a term for comparison.

    ``Node.js``, ``node js`` and ``NodeJS`` must all match, or the boundary
    rejects honest text and users learn to distrust it. ``+`` and ``#`` survive
    so ``c++`` and ``c#`` stay distinct from ``c``.
    """
    return _NOISE.sub("", term.strip().lower())


def _normalized_set(terms: Iterable[str]) -> set[str]:
    return {n for n in (normalize(t) for t in terms) if n}


class FactBoundaryOverrides(BaseModel):
    """User-set prohibitions. Stored, not derived."""

    model_config = ConfigDict(validate_assignment=True)

    profile_id: str = DEFAULT_PROFILE_ID
    never_claim: list[str] = Field(default_factory=list)


class FactBoundary(BaseModel):
    """What may be claimed, derived from confirmed facts only."""

    model_config = ConfigDict(frozen=True)

    profile_id: str = DEFAULT_PROFILE_ID
    allowed_skills: frozenset[str] = frozenset()
    preserved_orgs: frozenset[str] = frozenset()
    preserved_projects: frozenset[str] = frozenset()
    preserved_institutions: frozenset[str] = frozenset()
    claimable_credentials: frozenset[str] = frozenset()
    real_metrics: frozenset[str] = frozenset()
    never_claim: frozenset[str] = frozenset()

    # ── queries ──────────────────────────────────────────────────────────

    def is_forbidden(self, term: str) -> bool:
        """User-set prohibitions override every allowance."""
        return normalize(term) in self.never_claim

    def allows_skill(self, term: str) -> bool:
        return self._allows(term, self.allowed_skills)

    def allows_org(self, term: str) -> bool:
        return self._allows(term, self.preserved_orgs)

    def allows_project(self, term: str) -> bool:
        return self._allows(term, self.preserved_projects)

    def allows_institution(self, term: str) -> bool:
        return self._allows(term, self.preserved_institutions)

    def allows_credential(self, term: str) -> bool:
        """Exact match only. No fuzzy allowance for certifications."""
        return self._allows(term, self.claimable_credentials)

    def allows_metric(self, term: str) -> bool:
        return self._allows(term, self.real_metrics)

    def _allows(self, term: str, allowed: frozenset[str]) -> bool:
        key = normalize(term)
        if not key or key in self.never_claim:
            return False
        return key in allowed

    @property
    def is_empty(self) -> bool:
        """An empty boundary means nothing may be claimed at all.

        This is the correct state for a Brain with no confirmed facts, and
        callers must treat it as "cannot generate yet" rather than "no limits".
        """
        return not (
            self.allowed_skills
            or self.preserved_orgs
            or self.preserved_projects
            or self.preserved_institutions
            or self.claimable_credentials
        )


def derive(
    store: BrainStore, *, profile_id: str = DEFAULT_PROFILE_ID
) -> FactBoundary:
    """Build the boundary for a profile from confirmed records only."""

    def confirmed(model):
        return store.list(model, profile_id=profile_id, confirmed_only=True)

    skills = [s for s in confirmed(Skill) if s.has_evidence]
    experiences = confirmed(Experience)
    projects = confirmed(Project)
    education = confirmed(Education)
    credentials = [c for c in confirmed(Credential) if c.is_claimable]

    # Technologies named on confirmed work count as claimable skills; they are
    # evidenced by the record that mentions them.
    skill_terms: set[str] = {s.name for s in skills}
    for exp in experiences:
        skill_terms.update(exp.skills)
        skill_terms.update(exp.technologies)
    for proj in projects:
        skill_terms.update(proj.technologies)
        skill_terms.update(proj.skills_demonstrated)

    metrics: set[str] = set()
    for exp in experiences:
        metrics.update(a.metric for a in exp.achievements if a.verified and a.metric)
    for proj in projects:
        metrics.update(o.metric for o in proj.outcomes if o.verified and o.metric)

    overrides = store.get_singleton(FactBoundaryOverrides, profile_id=profile_id)
    never = _normalized_set(overrides.never_claim if overrides else [])

    def allowed(terms: Iterable[str]) -> frozenset[str]:
        return frozenset(_normalized_set(terms) - never)

    return FactBoundary(
        profile_id=profile_id,
        allowed_skills=allowed(skill_terms),
        preserved_orgs=allowed(e.org for e in experiences),
        preserved_projects=allowed(p.name for p in projects),
        preserved_institutions=allowed(e.institution for e in education),
        claimable_credentials=allowed(c.name for c in credentials),
        real_metrics=allowed(metrics),
        never_claim=frozenset(never),
    )
