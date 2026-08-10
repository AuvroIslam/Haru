"""Provenance: where every fact came from, and whether the user has confirmed it.

PRD §6.1 requires that every fact in the Brain carries its origin, a confidence,
and an explicit confirmation flag. This module defines those primitives.

The rule that matters most (PRD §6.3, §10.2): an unconfirmed fact may be stored
and shown, but it may never be used to widen the fact boundary. Imports land in a
review queue; the user confirms them before they can back a claim in a document.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


def utcnow() -> datetime:
    """Timezone-aware UTC now. Naive datetimes cause silent ordering bugs."""
    return datetime.now(timezone.utc)


class Source(str, Enum):
    """Where a fact came from. Ordered loosely from most to least trustworthy."""

    USER_ENTERED = "user_entered"
    FORM_ANSWER = "form_answer"
    DOCUMENT_EXTRACTION = "document_extraction"
    CV_IMPORT = "cv_import"
    GITHUB_IMPORT = "github_import"
    DEVPOST_IMPORT = "devpost_import"
    LINKEDIN_EXPORT = "linkedin_export"
    INFERRED = "inferred"


#: Sources a human typed or spoke directly. These may be auto-confirmed on entry;
#: everything else must pass through the review queue.
DIRECT_SOURCES: frozenset[Source] = frozenset(
    {Source.USER_ENTERED, Source.FORM_ANSWER}
)

# Default confidence by source. These are priors for the review queue's sort
# order, not measurements — a low value means "show this to the user sooner".
DEFAULT_CONFIDENCE: dict[Source, float] = {
    Source.USER_ENTERED: 1.0,
    Source.FORM_ANSWER: 1.0,
    Source.DOCUMENT_EXTRACTION: 0.7,
    Source.CV_IMPORT: 0.6,
    Source.GITHUB_IMPORT: 0.6,
    Source.DEVPOST_IMPORT: 0.6,
    Source.LINKEDIN_EXPORT: 0.7,
    Source.INFERRED: 0.3,
}


class Provenance(BaseModel):
    """The origin and confirmation state of a single fact."""

    model_config = ConfigDict(frozen=True)

    source: Source
    confidence: float = Field(ge=0.0, le=1.0)
    confirmed: bool = False
    confirmed_at: datetime | None = None
    recorded_at: datetime = Field(default_factory=utcnow)
    #: Free-text origin detail, e.g. a filename or repo URL.
    detail: str | None = None

    @model_validator(mode="after")
    def _confirmation_is_coherent(self) -> Provenance:
        if self.confirmed and self.confirmed_at is None:
            raise ValueError("confirmed provenance requires confirmed_at")
        if not self.confirmed and self.confirmed_at is not None:
            raise ValueError("confirmed_at set on unconfirmed provenance")
        return self

    @classmethod
    def create(
        cls,
        source: Source,
        *,
        confidence: float | None = None,
        detail: str | None = None,
        confirmed: bool = False,
    ) -> Provenance:
        """Build provenance, defaulting confidence from the source."""
        return cls(
            source=source,
            confidence=DEFAULT_CONFIDENCE[source] if confidence is None else confidence,
            confirmed=confirmed,
            confirmed_at=utcnow() if confirmed else None,
            detail=detail,
        )

    @classmethod
    def entered(cls, detail: str | None = None) -> Provenance:
        """Provenance for something the user typed. Confirmed by definition."""
        return cls.create(Source.USER_ENTERED, detail=detail, confirmed=True)

    def confirm(self) -> Provenance:
        """Return a confirmed copy. Provenance is frozen, so this is a new object."""
        if self.confirmed:
            return self
        return self.model_copy(
            update={"confirmed": True, "confirmed_at": utcnow()}
        )


class Attested(BaseModel, Generic[T]):
    """A value together with the provenance of that value.

    Used for fields that get assembled from several different imports — the
    identity block especially, where the name might come from a CV and the phone
    number from a passport scan.
    """

    value: T
    provenance: Provenance

    @property
    def is_confirmed(self) -> bool:
        return self.provenance.confirmed

    @classmethod
    def entered(cls, value: T, detail: str | None = None) -> Attested[T]:
        return cls(value=value, provenance=Provenance.entered(detail))

    @classmethod
    def imported(
        cls,
        value: T,
        source: Source,
        *,
        confidence: float | None = None,
        detail: str | None = None,
    ) -> Attested[T]:
        return cls(
            value=value,
            provenance=Provenance.create(source, confidence=confidence, detail=detail),
        )

    def confirm(self) -> Attested[T]:
        return self.model_copy(update={"provenance": self.provenance.confirm()})
