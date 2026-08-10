"""The immutable record of what was submitted (PRD §14.3).

"What exactly did I send them, and when?" is a question with real consequences
— most sharply on a government form, where the answer may be needed months
later and may need to be defensible.

So every submission produces a record of every field value *and where it came
from*, every document with its hash, every generated artifact, the full action
log, and which models were involved. The record carries a content digest, so a
later alteration is detectable rather than silent.

Nothing here is derived at read time. A record is a snapshot of what was true
at submission, kept even if the Brain changes afterwards.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from haru.brain.models import _new_id
from haru.brain.provenance import utcnow


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FieldEntry(BaseModel):
    """One value that was entered, and its provenance."""

    model_config = ConfigDict(frozen=True)

    label: str
    value: str
    source: str = ""
    confidence: float = 0.0
    #: True when the user confirmed this specific field (high-stakes mode).
    acknowledged: bool = False


class DocumentEntry(BaseModel):
    """A file that was uploaded, identified by content rather than name."""

    model_config = ConfigDict(frozen=True)

    filename: str
    digest: str
    size_bytes: int = 0
    consented: bool = False


class ActionEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: str
    performed: bool
    verified: bool
    note: str = ""


class EvidenceRecord(BaseModel):
    """An immutable account of one submission."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_id)
    at: datetime = Field(default_factory=utcnow)
    target_url: str = ""
    target_kind: str = ""
    org: str = ""
    high_stakes: bool = False
    fields: tuple[FieldEntry, ...] = ()
    documents: tuple[DocumentEntry, ...] = ()
    artifacts: dict[str, str] = Field(default_factory=dict)
    actions: tuple[ActionEntry, ...] = ()
    models_used: tuple[str, ...] = ()
    screenshots: tuple[str, ...] = ()
    approved_by_user: bool = False
    note: str = ""

    # ── integrity ────────────────────────────────────────────────────────

    def content(self) -> dict:
        """The parts that must not change. Excludes the digest itself."""
        return {
            "id": self.id,
            "at": self.at.isoformat(),
            "target_url": self.target_url,
            "target_kind": self.target_kind,
            "org": self.org,
            "high_stakes": self.high_stakes,
            "fields": [f.model_dump() for f in self.fields],
            "documents": [d.model_dump() for d in self.documents],
            "artifacts": self.artifacts,
            "actions": [a.model_dump() for a in self.actions],
            "models_used": list(self.models_used),
            "approved_by_user": self.approved_by_user,
        }

    def digest(self) -> str:
        """Content hash. A later edit changes this, so tampering is visible."""
        payload = json.dumps(self.content(), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8"))

    def verify(self, expected: str) -> bool:
        return self.digest() == expected

    # ── output ───────────────────────────────────────────────────────────

    def to_json(self) -> str:
        return json.dumps(
            {**self.content(), "digest": self.digest()}, indent=2, ensure_ascii=False
        )

    def write(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_json(), encoding="utf-8")
        return target

    def summary(self) -> str:
        parts = [
            f"{self.target_kind or 'submission'} to {self.org or self.target_url or 'unknown'}",
            self.at.strftime("%Y-%m-%d %H:%M UTC"),
            f"{len(self.fields)} fields",
        ]
        if self.documents:
            parts.append(f"{len(self.documents)} documents")
        if self.high_stakes:
            parts.append("high-stakes")
        parts.append(f"digest {self.digest()[:12]}")
        return " · ".join(parts)

    @property
    def unverified_actions(self) -> tuple[ActionEntry, ...]:
        return tuple(a for a in self.actions if a.performed and not a.verified)


def build_record(
    plan,
    *,
    steps=(),
    models_used: tuple[str, ...] = (),
    screenshots: tuple[str, ...] = (),
    documents: tuple[DocumentEntry, ...] = (),
    high_stakes: bool = False,
    acknowledged: set[str] | None = None,
    approved_by_user: bool = False,
    note: str = "",
) -> EvidenceRecord:
    """Capture what an :class:`~haru.adapters.plan.ApplicationPlan` submitted."""
    confirmed = acknowledged or set()
    return EvidenceRecord(
        target_url=getattr(plan, "url", ""),
        target_kind=getattr(getattr(plan, "ask", None), "role", "") or "application",
        org=getattr(getattr(plan, "ask", None), "org", "") or "",
        high_stakes=high_stakes,
        fields=tuple(
            FieldEntry(
                label=field.label,
                value=field.match.value or "",
                source=field.match.source,
                confidence=field.match.confidence,
                acknowledged=field.label in confirmed,
            )
            for field in plan.to_fill
        ),
        documents=tuple(documents),
        artifacts=dict(getattr(plan, "generated", {}) or {}),
        actions=tuple(
            ActionEntry(
                action=step.action.describe(),
                performed=step.performed,
                verified=step.verified,
                note=step.note,
            )
            for step in steps
        ),
        models_used=tuple(models_used),
        screenshots=tuple(screenshots),
        approved_by_user=approved_by_user,
        note=note,
    )
