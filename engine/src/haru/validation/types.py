"""Validation vocabulary and the severity policy (PRD §10.2).

The *detectors* land in M3. The *policy* lands here, in M0, deliberately: which
checks may be downgraded by a mode is a safety decision, and encoding it now
means M3 can only supply detection, not relax the rules.

Policy, restated from the PRD:

* Fact boundary — blocking in every mode. Not relaxable.
* Credentials    — blocking in every mode. "No exceptions, no modes."
* Model leakage  — blocking in every mode. Pure output corruption.
* Cliché         — the only check a mode may soften.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from haru.brain.provenance import utcnow


class ArtifactKind(str, Enum):
    """What is being validated. Determines which detectors apply in M3."""

    CV_BULLET = "cv_bullet"
    CV_SUMMARY = "cv_summary"
    COVER_LETTER = "cover_letter"
    APPLICATION_ANSWER = "application_answer"
    HACKATHON_STORY = "hackathon_story"
    FORM_FREE_TEXT = "form_free_text"


class Check(str, Enum):
    FACT_BOUNDARY = "fact_boundary"
    CREDENTIAL = "credential"
    MODEL_LEAKAGE = "model_leakage"
    CLICHE = "cliche"
    REPO_GROUNDING = "repo_grounding"


class Severity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    IGNORED = "ignored"


class ValidationMode(str, Enum):
    STRICT = "strict"
    NORMAL = "normal"
    LENIENT = "lenient"


#: Checks no mode may soften. Guarded by test, not just convention.
UNRELAXABLE: frozenset[Check] = frozenset(
    {Check.FACT_BOUNDARY, Check.CREDENTIAL, Check.MODEL_LEAKAGE, Check.REPO_GROUNDING}
)

_CLICHE_BY_MODE: dict[ValidationMode, Severity] = {
    ValidationMode.STRICT: Severity.BLOCKING,
    ValidationMode.NORMAL: Severity.WARNING,
    ValidationMode.LENIENT: Severity.IGNORED,
}


def severity_for(check: Check, mode: ValidationMode) -> Severity:
    """Resolve a check's severity under a mode.

    Everything except the cliché filter is blocking regardless of mode.
    """
    if check in UNRELAXABLE:
        return Severity.BLOCKING
    if check is Check.CLICHE:
        return _CLICHE_BY_MODE[mode]
    raise ValueError(f"no severity policy for {check}")


class Artifact(BaseModel):
    """A piece of generated text on its way to a form."""

    model_config = ConfigDict(frozen=True)

    kind: ArtifactKind
    text: str
    profile_id: str = "default"
    #: Free-form context for detectors — target org, question asked, repo path.
    context: dict[str, str] = Field(default_factory=dict)


class Violation(BaseModel):
    model_config = ConfigDict(frozen=True)

    check: Check
    severity: Severity
    message: str
    #: The offending span, when the detector can identify one.
    term: str | None = None

    def __str__(self) -> str:
        where = f" ({self.term!r})" if self.term else ""
        return f"[{self.severity.value}] {self.check.value}{where}: {self.message}"


class Result(BaseModel):
    """Outcome of validating one artifact."""

    model_config = ConfigDict(frozen=True)

    artifact: Artifact
    mode: ValidationMode
    violations: tuple[Violation, ...] = ()
    #: True when no real detector ran — the M0 stub sets this.
    stubbed: bool = False
    checked_at: object = Field(default_factory=utcnow)

    @property
    def blocking(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.BLOCKING)

    @property
    def warnings(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.WARNING)

    @property
    def passed(self) -> bool:
        """Whether the artifact may proceed. Warnings do not block."""
        return not self.blocking

    def raise_if_blocked(self) -> None:
        if self.blocking:
            raise FactBoundaryViolation(self)


class FactBoundaryViolation(Exception):
    """Raised when blocked content is used anyway.

    Carries the full result so callers can show the user exactly what could not
    be produced honestly (PRD §10.2).
    """

    def __init__(self, result: Result) -> None:
        self.result = result
        detail = "; ".join(str(v) for v in result.blocking)
        super().__init__(f"{result.artifact.kind.value} blocked: {detail}")
