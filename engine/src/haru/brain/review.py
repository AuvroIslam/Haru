"""The review queue: nothing enters the Brain confirmed without a human (PRD §6.3).

Imports land unconfirmed. Until a person confirms a record it can be stored,
listed and shown, but it cannot widen the fact boundary — so it cannot back a
claim in anything Haru generates.

Editing is treated as taking ownership: when a user changes an imported value,
the stored provenance becomes ``USER_ENTERED``, because the value on disk is now
theirs rather than the parser's. The parser's original survives in
``record_history`` (PRD §6.1), so the audit trail is not lost.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict

from haru.brain.models import DEFAULT_PROFILE_ID, BrainRecord, Credential, Skill
from haru.brain.provenance import Provenance, Source, utcnow
from haru.brain.store import BrainStore, record_kind

R = TypeVar("R", bound=BrainRecord)


class ReviewItem(BaseModel):
    """A pending record plus why it wants attention."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    record: BrainRecord
    reasons: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return record_kind(type(self.record))

    @property
    def confidence(self) -> float:
        return self.record.provenance.confidence


def _reasons_for(record: BrainRecord) -> tuple[str, ...]:
    """Explain why this record needs a human.

    The queue sorts by attention needed, so these double as ranking signal —
    the same idea as the batch review surface in PRD §14.4.
    """
    reasons: list[str] = []
    prov = record.provenance

    if prov.confidence < 0.5:
        reasons.append(f"low confidence ({prov.confidence:.0%})")
    if prov.source is Source.INFERRED:
        reasons.append("inferred, not stated by you")

    if isinstance(record, Credential):
        if record.document_ref is None:
            reasons.append("no supporting document — cannot be claimed until provided")
        if record.is_expired():
            reasons.append("expired")
    if isinstance(record, Skill) and not record.has_evidence:
        reasons.append("no evidence linking it to real work")

    return tuple(reasons)


class ReviewQueue:
    """Confirm, edit or reject imported facts."""

    def __init__(self, store: BrainStore) -> None:
        self.store = store

    # ── reading ──────────────────────────────────────────────────────────

    def pending(
        self, *, profile_id: str = DEFAULT_PROFILE_ID, limit: int | None = None
    ) -> list[ReviewItem]:
        """Unconfirmed records, most in need of attention first."""
        records = self.store.unconfirmed(profile_id=profile_id)
        items = [ReviewItem(record=r, reasons=_reasons_for(r)) for r in records]
        items.sort(key=lambda i: (-len(i.reasons), i.confidence))
        return items[:limit] if limit is not None else items

    def count(self, *, profile_id: str = DEFAULT_PROFILE_ID) -> int:
        return len(self.store.unconfirmed(profile_id=profile_id))

    def is_empty(self, *, profile_id: str = DEFAULT_PROFILE_ID) -> bool:
        return self.count(profile_id=profile_id) == 0

    # ── acting ───────────────────────────────────────────────────────────

    def confirm(self, record: R) -> R:
        """Accept a record as-is. It may now back generated claims."""
        if record.provenance.confirmed:
            return record
        return self.store.put(
            record.model_copy(
                update={
                    "provenance": record.provenance.confirm(),
                    "updated_at": utcnow(),
                }
            )
        )

    def confirm_many(self, records: Iterable[R]) -> list[R]:
        return [self.confirm(r) for r in records]

    def edit(self, record: R, **changes: Any) -> R:
        """Change values and confirm.

        Provenance becomes ``USER_ENTERED``: the stored value is now the user's,
        not the importer's. The prior version is archived by the store.
        """
        if not changes:
            return self.confirm(record)
        return self.store.put(
            record.model_copy(
                update={
                    **changes,
                    "provenance": Provenance.entered(
                        detail=f"edited during review (was {record.provenance.source.value})"
                    ),
                    "updated_at": utcnow(),
                }
            )
        )

    def reject(self, record: BrainRecord) -> bool:
        """Discard a record entirely."""
        return self.store.delete(type(record), record.id)

    def reject_many(self, records: Iterable[BrainRecord]) -> int:
        return sum(1 for r in records if self.reject(r))

    def confirm_clean(
        self, *, profile_id: str = DEFAULT_PROFILE_ID
    ) -> Sequence[BrainRecord]:
        """Bulk-confirm only records with nothing flagged.

        The same rule as batch review (PRD §14.4): the routine tail may be
        accepted together, anything flagged must be looked at individually.
        """
        clean = [i.record for i in self.pending(profile_id=profile_id) if not i.reasons]
        return self.confirm_many(clean)
