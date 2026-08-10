"""Checking a project write-up against the project (PRD §8.2, §10.2).

The fact boundary stops Haru claiming skills the user does not have. This does
the same job one level down: it stops a submission claiming the *project* uses
technology the repository does not contain.

The rule is the same as everywhere else — a claim must have evidence — and so
is the exception: naming something as considered, rejected, or someone else's
is a mention, not a claim.

It also reports the reverse. Real work present in the repository but absent
from the draft is surfaced as a *suggestion*, never a violation: under-claiming
is not dishonest, but it does lose the user credit they earned.
"""

from __future__ import annotations

from dataclasses import dataclass

from haru.adapters.repo import RepoFacts
from haru.brain.fact_boundary import FactBoundary
from haru.validation.detect import canonical, find_lowercase_tech, find_mentions
from haru.validation.lexicon import GENERIC_TECH, KNOWN_TECH, ROLE_WORDS
from haru.validation.types import (
    Artifact,
    ArtifactKind,
    Check,
    Result,
    Severity,
    ValidationMode,
    Violation,
)
from haru.validation.validator import FactBoundaryValidator

#: Only these artifacts are checked against a repository.
GROUNDED_KINDS: frozenset[ArtifactKind] = frozenset({ArtifactKind.HACKATHON_STORY})


@dataclass(frozen=True)
class Omission:
    """Something real the draft failed to mention."""

    term: str

    def __str__(self) -> str:
        return f"{self.term} is in the repository but not mentioned"


def claimed_technologies(text: str) -> list[str]:
    """Technologies the text claims the project uses."""
    claims: list[str] = []
    seen: set[str] = set()

    for mention in list(find_mentions(text)) + list(find_lowercase_tech(text, KNOWN_TECH)):
        key = mention.key
        if not key or key in seen or not mention.is_claim:
            continue
        if key in GENERIC_TECH or key in ROLE_WORDS:
            continue
        seen.add(key)
        claims.append(mention.text)
    return claims


def find_omissions(text: str, repo: RepoFacts, *, limit: int = 8) -> list[Omission]:
    """Real dependencies and languages the draft never mentions."""
    mentioned = {canonical(term) for term in claimed_technologies(text)}
    # The project's own name is not a technology it "forgot to mention", and
    # listing it as one just adds noise to a set of suggestions whose value
    # depends on being short.
    own_names = {canonical(n) for n in (repo.name, repo.root.name) if n}
    missing = [
        item
        for item in sorted(repo.evidence)
        if canonical(item) not in mentioned
        and canonical(item) not in GENERIC_TECH
        and canonical(item) not in own_names
    ]
    return [Omission(term=item) for item in missing[:limit]]


class RepoGroundedValidator:
    """Fact boundary, plus the repository for project write-ups.

    Wraps rather than replaces :class:`FactBoundaryValidator`: a hackathon
    submission still must not claim credentials the user lacks, so both sets of
    checks apply.
    """

    def __init__(
        self,
        repo: RepoFacts | None = None,
        *,
        inner: FactBoundaryValidator | None = None,
        team: tuple[str, ...] = (),
        event: str | None = None,
    ) -> None:
        self.repo = repo
        self.inner = inner or FactBoundaryValidator()
        #: Teammates and the event, supplied by the user with the submission.
        #:
        #: The fact boundary exists to stop the user claiming capabilities,
        #: employers or credentials they do not have. A collaborator's name and
        #: the hackathon's name are neither — but they are proper nouns, and
        #: nothing syntactic separates "Grace" from "Google". Rather than
        #: loosening the boundary, the user states them, and only those exact
        #: strings are permitted. The widening is a user-supplied fact, not a
        #: model-supplied one.
        self.context_entities = frozenset(
            canonical(name) for name in (*team, event or "") if name
        )
        #: Populated on each validate() so a caller can show them to the user.
        self.omissions: list[Omission] = []

    def validate(
        self,
        artifact: Artifact,
        boundary: FactBoundary,
        mode: ValidationMode = ValidationMode.NORMAL,
    ) -> Result:
        if self.context_entities and artifact.kind in GROUNDED_KINDS:
            boundary = boundary.model_copy(
                update={
                    "preserved_projects": boundary.preserved_projects
                    | self.context_entities
                }
            )

        result = self.inner.validate(artifact, boundary, mode)
        if self.repo is None or artifact.kind not in GROUNDED_KINDS:
            return result

        violations = list(result.violations)
        for term in claimed_technologies(artifact.text):
            if self.repo.supports(term):
                continue
            # Only flag terms that are demonstrably technologies. Otherwise the
            # project's own name, a teammate, or the hackathon itself would be
            # reported as "not in the repository" — over-blocking that would
            # make the check useless, since it would fire on every draft.
            if canonical(term) not in KNOWN_TECH:
                continue
            # A term the *person* owns but the *project* does not use is still
            # a false claim about this project.
            violations.append(
                Violation(
                    check=Check.REPO_GROUNDING,
                    severity=Severity.BLOCKING,
                    message=(
                        f"the repository does not contain this — "
                        f"{self.repo.summary()}"
                    ),
                    term=term,
                )
            )

        self.omissions = find_omissions(artifact.text, self.repo)
        return result.model_copy(update={"violations": tuple(violations)})


def install(repo: RepoFacts) -> RepoGroundedValidator:
    """Make repo-grounded validation active for a submission."""
    from haru.validation.seam import set_validator

    validator = RepoGroundedValidator(repo)
    set_validator(validator)
    return validator
