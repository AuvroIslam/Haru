"""The Personal Brain schema (PRD §6.2).

Design rules this file enforces structurally rather than by convention:

* Every list record carries provenance and a version (PRD §6.1).
* Fields holding PII are *marked* sensitive in the schema itself, so the model
  router's redaction layer (PRD §13.2) can enumerate them instead of relying on
  a hand-maintained list that will drift.
* ``profile_id`` exists on every record from day one. Whether the product ships
  one profile or several is still open (PRD §20 Q4), but adding the column later
  is a migration and carrying it unused costs nothing.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticUndefined

from haru.brain.provenance import Attested, Provenance, today, utcnow

DEFAULT_PROFILE_ID = "default"


def _new_id() -> str:
    return uuid.uuid4().hex


def sensitive(default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    """Mark a field as PII. See :func:`sensitive_paths`.

    Accepts either ``default`` or ``default_factory``; passing both to
    ``Field`` is an error, so only the one supplied is forwarded.
    """
    extra = dict(kwargs.pop("json_schema_extra", None) or {})
    extra["sensitive"] = True
    if "default_factory" in kwargs:
        return Field(json_schema_extra=extra, **kwargs)
    if default is PydanticUndefined:
        default = None
    return Field(default, json_schema_extra=extra, **kwargs)


def sensitive_paths(model: type[BaseModel], _prefix: str = "") -> list[str]:
    """Return dotted paths of every field marked sensitive, recursively.

    The redaction layer uses this to guarantee that nothing marked sensitive is
    ever included in a cloud request (PRD §13.2 rule 1).
    """
    paths: list[str] = []
    for name, field in model.model_fields.items():
        path = f"{_prefix}{name}"
        extra = field.json_schema_extra or {}
        if isinstance(extra, dict) and extra.get("sensitive"):
            paths.append(path)
        for candidate in _nested_models(field.annotation):
            paths.extend(sensitive_paths(candidate, f"{path}."))
    return paths


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    """Pull BaseModel subclasses out of an annotation, including containers."""
    found: list[type[BaseModel]] = []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    for arg in getattr(annotation, "__args__", ()):
        found.extend(_nested_models(arg))
    return found


# ── Enums ────────────────────────────────────────────────────────────────────


class EmploymentType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    FREELANCE = "freelance"
    VOLUNTEER = "volunteer"


class Proficiency(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class RemotePreference(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    NO_PREFERENCE = "no_preference"


class Tone(str, Enum):
    FORMAL = "formal"
    WARM = "warm"
    DIRECT = "direct"
    ACADEMIC = "academic"


#: The default for every voluntary disclosure field (PRD §16.3). These are
#: protected-characteristic questions; declining is the only safe default.
DECLINE = "decline_to_self_identify"


# ── Base ─────────────────────────────────────────────────────────────────────


class BrainRecord(BaseModel):
    """Common envelope for every stored Brain entity."""

    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=_new_id)
    profile_id: str = DEFAULT_PROFILE_ID
    provenance: Provenance
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    version: int = 1

    @property
    def is_confirmed(self) -> bool:
        """Only confirmed records may back a claim in generated output."""
        return self.provenance.confirmed


# ── Entities ─────────────────────────────────────────────────────────────────


class Link(BaseModel):
    label: str
    url: str


class Identity(BaseModel):
    """Assembled from many sources, so provenance is per field."""

    model_config = ConfigDict(validate_assignment=True)

    profile_id: str = DEFAULT_PROFILE_ID
    legal_name: Attested[str] | None = None
    preferred_name: Attested[str] | None = None
    pronouns: Attested[str] | None = None
    emails: list[Attested[str]] = Field(default_factory=list)
    phones: list[Attested[str]] = Field(default_factory=list)
    street: Attested[str] | None = None
    city: Attested[str] | None = None
    region: Attested[str] | None = None
    country: Attested[str] | None = None
    postal_code: Attested[str] | None = None
    date_of_birth: Attested[date] | None = sensitive()
    national_ids: list[Attested[str]] = sensitive(default_factory=list)
    links: list[Link] = Field(default_factory=list)


class WorkAuthorization(BaseModel):
    """Asked by essentially every job application; omitted by most tools."""

    model_config = ConfigDict(validate_assignment=True)

    profile_id: str = DEFAULT_PROFILE_ID
    citizenships: list[str] = Field(default_factory=list)
    legally_authorized_in: list[str] = Field(default_factory=list)
    requires_sponsorship: bool | None = None
    permit_type: str | None = None
    permit_expiry: date | None = None
    visa_status: str | None = sensitive()


class Availability(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    profile_id: str = DEFAULT_PROFILE_ID
    earliest_start_date: date | None = None
    open_to: list[EmploymentType] = Field(default_factory=list)
    notice_period: str | None = None
    relocation_willing: bool | None = None
    remote_preference: RemotePreference = RemotePreference.NO_PREFERENCE


class Compensation(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    profile_id: str = DEFAULT_PROFILE_ID
    expectation: int | None = None
    range_min: int | None = None
    range_max: int | None = None
    currency: str = "USD"
    #: Illegal to ask in many jurisdictions; left blank by default (PRD §16.3).
    current_salary: int | None = sensitive()


class Achievement(BaseModel):
    """A single accomplishment. ``metric`` feeds the fact boundary's real_metrics."""

    text: str
    metric: str | None = None
    skills: list[str] = Field(default_factory=list)
    #: True only when the user has confirmed the metric is accurate.
    verified: bool = False


class Education(BrainRecord):
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    grade: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    expected_end_date: date | None = None
    thesis: str | None = None
    honors: list[str] = Field(default_factory=list)
    relevant_coursework: list[str] = Field(default_factory=list)
    transcript_ref: str | None = None


class Experience(BrainRecord):
    org: str
    title: str
    location: str | None = None
    employment_type: EmploymentType | None = None
    start_date: date | None = None
    end_date: date | None = None
    summary: str | None = None
    achievements: list[Achievement] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Project(BrainRecord):
    name: str
    tagline: str | None = None
    description: str | None = None
    role: str | None = None
    team_size: int | None = None
    duration: str | None = None
    technologies: list[str] = Field(default_factory=list)
    skills_demonstrated: list[str] = Field(default_factory=list)
    repo_url: str | None = None
    live_url: str | None = None
    demo_video: str | None = None
    outcomes: list[Achievement] = Field(default_factory=list)
    media_refs: list[str] = Field(default_factory=list)


class Skill(BrainRecord):
    name: str
    category: str | None = None
    proficiency: Proficiency | None = None
    years_used: float | None = None
    last_used: date | None = None
    #: Ids of Experience/Project records that demonstrate this skill. A skill
    #: with no evidence cannot enter the fact boundary (PRD §10.2).
    evidence_refs: list[str] = Field(default_factory=list)

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence_refs)


class Credential(BrainRecord):
    """Certifications. Never stretchable — see PRD §10.2.

    A credential may only back a claim when it is confirmed *and* has a
    supporting document. ``is_claimable`` is the single check for that.
    """

    name: str
    issuer: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    credential_id: str | None = None
    verify_url: str | None = None
    document_ref: str | None = None

    @property
    def is_claimable(self) -> bool:
        return self.is_confirmed and self.document_ref is not None

    def is_expired(self, on: date | None = None) -> bool:
        if self.expiry_date is None:
            return False
        return self.expiry_date < (on or today())


class WritingSample(BrainRecord):
    """Prose the user actually wrote, used to match their voice (PRD §10.3)."""

    title: str | None = None
    text: str
    context: str | None = None


class QuestionBankEntry(BrainRecord):
    canonical_question: str
    variants: list[str] = Field(default_factory=list)
    base_answer: str | None = None
    outcome_signal: float | None = None


class VoluntaryDisclosure(BaseModel):
    """Protected characteristics. Defaults decline; never leaves the device."""

    model_config = ConfigDict(validate_assignment=True)

    profile_id: str = DEFAULT_PROFILE_ID
    gender: str = sensitive(default=DECLINE)
    race_ethnicity: str = sensitive(default=DECLINE)
    veteran_status: str = sensitive(default=DECLINE)
    disability_status: str = sensitive(default=DECLINE)


class StandardAnswers(BaseModel):
    """The boring universal questions almost every application repeats."""

    model_config = ConfigDict(validate_assignment=True)

    profile_id: str = DEFAULT_PROFILE_ID
    age_18_or_over: bool | None = None
    background_check_consent: bool | None = None
    criminal_record: bool | None = sensitive()
    previously_employed_here: bool | None = None
    how_did_you_hear: str | None = None


class Pacing(BaseModel):
    """User-set submission pacing. Off by default — see PRD §19."""

    min_seconds_between_submissions: int | None = None
    max_per_day: int | None = None


class Preferences(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    profile_id: str = DEFAULT_PROFILE_ID
    cv_template_ids: list[str] = Field(default_factory=list)
    tone: Tone = Tone.DIRECT
    target_roles: list[str] = Field(default_factory=list)
    target_industries: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    pacing: Pacing = Field(default_factory=Pacing)
