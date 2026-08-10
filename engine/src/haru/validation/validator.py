"""The fact-boundary validator (PRD §10.2) — M3.

Installs behind the seam built in M0, so nothing that calls
:func:`haru.validation.seam.validate` changes. Installing it also lifts the
interlock that blocks submission while validation is stubbed (PRD §17.1).

Four checks, three of them blocking in every mode:

======================  =========================================================
fact boundary           entities claimed as the writer's own must be on file
credential              certifications must be confirmed *and* evidenced
model leakage           the model must not address its operator in the output
cliché                  the only check a mode may soften
======================  =========================================================

What this does and does not catch
---------------------------------
Detection is pattern-based, not semantic. It reliably catches named entities
claimed as the writer's own — the shape almost every résumé fabrication takes.
It will miss a fabrication phrased entirely in lowercase words absent from
:data:`~haru.validation.lexicon.KNOWN_TECH`, and it cannot judge whether a
truthful-looking sentence describes work that actually happened.

That limitation is worth stating plainly rather than papering over: this is a
floor, not a ceiling. It is combined with a human approval gate on every
submission precisely because neither mechanism is sufficient alone.
"""

from __future__ import annotations

from haru.brain.fact_boundary import FactBoundary
from haru.validation.detect import (
    Mention,
    canonical,
    contains_phrase,
    find_credential_claims,
    find_lowercase_tech,
    find_mentions,
    find_numeric_claims,
)
from haru.validation.lexicon import (
    CLICHES,
    CREDENTIAL_MARKERS,
    GENERIC_TECH,
    KNOWN_TECH,
    LEAK_PHRASES,
    ROLE_WORDS,
)
from haru.validation.types import (
    Artifact,
    Check,
    Result,
    Severity,
    ValidationMode,
    Violation,
    severity_for,
)


def _allowed_anywhere(boundary: FactBoundary, key: str) -> bool:
    """Is this term on file as anything at all?"""
    return (
        key in boundary.allowed_skills
        or key in boundary.preserved_orgs
        or key in boundary.preserved_projects
        or key in boundary.preserved_institutions
        or key in boundary.claimable_credentials
    )


class FactBoundaryValidator:
    """Judges generated text against what the user has actually confirmed."""

    def __init__(self, *, extra_known_tech: frozenset[str] | None = None) -> None:
        self.known_tech = KNOWN_TECH | (extra_known_tech or frozenset())

    def validate(
        self,
        artifact: Artifact,
        boundary: FactBoundary,
        mode: ValidationMode = ValidationMode.NORMAL,
    ) -> Result:
        text = artifact.text
        violations: list[Violation] = []

        violations.extend(self._leakage(text))
        credentials, credential_terms = self._credentials(text, boundary)
        violations.extend(credentials)
        violations.extend(self._entities(text, boundary, credential_terms))
        violations.extend(self._metrics(text, boundary))
        violations.extend(self._cliches(text, mode))

        return Result(
            artifact=artifact,
            mode=mode,
            violations=tuple(violations),
            stubbed=False,
        )

    # ── checks ───────────────────────────────────────────────────────────

    def _leakage(self, text: str) -> list[Violation]:
        return [
            Violation(
                check=Check.MODEL_LEAKAGE,
                severity=severity_for(Check.MODEL_LEAKAGE, ValidationMode.NORMAL),
                message="the model is addressing its operator inside the output",
                term=phrase,
            )
            for phrase in LEAK_PHRASES
            if contains_phrase(text, phrase)
        ]

    def _credentials(
        self, text: str, boundary: FactBoundary
    ) -> tuple[list[Violation], set[str]]:
        """Certifications are never stretchable, in any mode."""
        violations: list[Violation] = []
        handled: set[str] = set()

        for mention in find_credential_claims(text, CREDENTIAL_MARKERS):
            if not mention.is_claim:
                continue
            if not mention.text:
                violations.append(
                    Violation(
                        check=Check.CREDENTIAL,
                        severity=Severity.BLOCKING,
                        message=(
                            "claims a certification without naming one, so it "
                            "cannot be checked against your credentials"
                        ),
                    )
                )
                continue

            handled.add(mention.key)
            if not boundary.allows_credential(mention.text):
                violations.append(
                    Violation(
                        check=Check.CREDENTIAL,
                        severity=Severity.BLOCKING,
                        message=(
                            "no confirmed credential with a supporting document "
                            "matches this"
                        ),
                        term=mention.text,
                    )
                )
        return violations, handled

    def _entities(
        self, text: str, boundary: FactBoundary, already_checked: set[str]
    ) -> list[Violation]:
        if boundary.is_empty:
            return [
                Violation(
                    check=Check.FACT_BOUNDARY,
                    severity=Severity.BLOCKING,
                    message=(
                        "nothing has been confirmed in the Brain yet, so no claim "
                        "can be supported"
                    ),
                )
            ]

        mentions: list[Mention] = find_mentions(text)
        mentions += find_lowercase_tech(text, self.known_tech)

        violations: list[Violation] = []
        seen: set[str] = set(already_checked)

        for mention in mentions:
            key = mention.key
            if not key or key in seen:
                continue
            if not mention.is_claim:
                continue  # someone else's, or explicitly disclaimed
            # Strip architectural vocabulary out of the run first: "REST APIs"
            # is entirely generic, while "REST Django" should report Django.
            core = [
                token
                for token in mention.text.split()
                if canonical(token) not in GENERIC_TECH
            ]
            if not core:
                continue
            if core != mention.text.split():
                mention = Mention(
                    text=" ".join(core),
                    disclaimed=mention.disclaimed,
                    third_party=mention.third_party,
                )
                key = mention.key
                if key in seen:
                    continue

            if " " not in mention.text and key in ROLE_WORDS:
                continue  # a bare job title is not a claim about an entity
            if any(marker in mention.text.lower() for marker in CREDENTIAL_MARKERS):
                continue  # the credential check owns this one

            seen.add(key)
            if boundary.is_forbidden(mention.text):
                violations.append(
                    Violation(
                        check=Check.FACT_BOUNDARY,
                        severity=Severity.BLOCKING,
                        message="you asked never to claim this",
                        term=mention.text,
                    )
                )
            elif not _allowed_anywhere(boundary, key):
                violations.append(
                    Violation(
                        check=Check.FACT_BOUNDARY,
                        severity=Severity.BLOCKING,
                        message=(
                            "not among your confirmed skills, employers, projects "
                            "or institutions"
                        ),
                        term=mention.text,
                    )
                )
        return violations

    def _metrics(self, text: str, boundary: FactBoundary) -> list[Violation]:
        violations: list[Violation] = []
        for number, spans in find_numeric_claims(text):
            if any(boundary.allows_metric(span) for span in spans):
                continue
            if any(canonical(span) in boundary.allowed_skills for span in spans):
                continue  # e.g. a version number that is part of a skill name
            violations.append(
                Violation(
                    check=Check.FACT_BOUNDARY,
                    severity=Severity.BLOCKING,
                    message=(
                        "figure is not among your verified metrics — only numbers "
                        "you have confirmed may be cited"
                    ),
                    term=spans[-1] if spans else number,
                )
            )
        return violations

    def _cliches(self, text: str, mode: ValidationMode) -> list[Violation]:
        severity = severity_for(Check.CLICHE, mode)
        if severity is Severity.IGNORED:
            return []
        return [
            Violation(
                check=Check.CLICHE,
                severity=severity,
                message="reads as machine-written",
                term=phrase,
            )
            for phrase in sorted(CLICHES)
            if contains_phrase(text, phrase)
        ]


def install(**kwargs) -> None:
    """Make the real validator active, replacing the M0 stub."""
    from haru.validation.seam import set_validator

    set_validator(FactBoundaryValidator(**kwargs))
