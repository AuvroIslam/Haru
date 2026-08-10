"""Reviewable diff between two CVs (PRD §11.4).

Before any CV is used the user sees exactly what changed and why — every change
attributed to the requirement that caused it, and every one individually
vetoable. Presenting a tailored CV without this would ask the user to trust
selection they cannot inspect, which is the same failure as generating prose
they will not read.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from haru.cv.models import RenderedSection, Slot, TailoredCV


class ChangeKind(str, Enum):
    ITEM_ADDED = "item_added"
    ITEM_REMOVED = "item_removed"
    ITEM_REORDERED = "item_reordered"
    HEADING_CHANGED = "heading_changed"
    SECTION_ADDED = "section_added"
    SECTION_REMOVED = "section_removed"
    SUMMARY_CHANGED = "summary_changed"


class Change(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ChangeKind
    slot: Slot
    description: str
    reason: str
    record_id: str | None = None

    def __str__(self) -> str:
        return f"{self.description} — {self.reason}"


def _by_slot(cv: TailoredCV) -> dict[Slot, RenderedSection]:
    return {s.slot: s for s in cv.sections}


def diff(master: TailoredCV, tailored: TailoredCV) -> list[Change]:
    """Describe what tailoring did to the master CV."""
    changes: list[Change] = []
    left, right = _by_slot(master), _by_slot(tailored)

    for slot in right.keys() - left.keys():
        changes.append(
            Change(
                kind=ChangeKind.SECTION_ADDED,
                slot=slot,
                description=f"Added section '{right[slot].heading}'",
                reason="not present in the master CV",
            )
        )
    for slot in left.keys() - right.keys():
        changes.append(
            Change(
                kind=ChangeKind.SECTION_REMOVED,
                slot=slot,
                description=f"Removed section '{left[slot].heading}'",
                reason="no confirmed content matched this target",
            )
        )

    for slot in left.keys() & right.keys():
        changes.extend(_diff_section(left[slot], right[slot]))

    return changes


def _diff_section(before: RenderedSection, after: RenderedSection) -> list[Change]:
    changes: list[Change] = []
    slot = after.slot

    if before.heading != after.heading:
        changes.append(
            Change(
                kind=ChangeKind.HEADING_CHANGED,
                slot=slot,
                description=f"Renamed '{before.heading}' to '{after.heading}'",
                reason="template heading label for this target",
            )
        )

    if slot is Slot.SUMMARY and before.text != after.text:
        changes.append(
            Change(
                kind=ChangeKind.SUMMARY_CHANGED,
                slot=slot,
                description="Rewrote the summary",
                reason="emphasises skills this target asked for",
            )
        )

    before_ids = [i.record_id for i in before.items]
    after_ids = [i.record_id for i in after.items]
    before_map = {i.record_id: i for i in before.items}

    for item in after.items:
        if item.record_id not in before_map:
            changes.append(
                Change(
                    kind=ChangeKind.ITEM_ADDED,
                    slot=slot,
                    description=f"Added '{item.title}'",
                    reason=item.reason,
                    record_id=item.record_id,
                )
            )
    for item in before.items:
        if item.record_id not in {i.record_id for i in after.items}:
            changes.append(
                Change(
                    kind=ChangeKind.ITEM_REMOVED,
                    slot=slot,
                    description=f"Removed '{item.title}'",
                    reason="less relevant to this target than the items kept",
                    record_id=item.record_id,
                )
            )

    kept_before = [i for i in before_ids if i in set(after_ids)]
    kept_after = [i for i in after_ids if i in set(before_ids)]
    if kept_before != kept_after and len(kept_before) > 1:
        changes.append(
            Change(
                kind=ChangeKind.ITEM_REORDERED,
                slot=slot,
                description=f"Reordered {after.heading.lower()}",
                reason="most relevant to this target first",
            )
        )

    return changes


def summarize(changes: list[Change]) -> str:
    if not changes:
        return "No changes from the master CV."
    counts: dict[ChangeKind, int] = {}
    for change in changes:
        counts[change.kind] = counts.get(change.kind, 0) + 1
    parts = [f"{n} {kind.value.replace('_', ' ')}" for kind, n in sorted(counts.items(), key=lambda kv: kv[0].value)]
    return ", ".join(parts)
