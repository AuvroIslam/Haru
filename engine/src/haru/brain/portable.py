"""Export and import the whole Brain as plain JSON (PRD P2).

"The user owns the record. No lock-in." That is only true if leaving is easy,
so export exists from the first milestone rather than as a later feature — it is
much harder to add convincingly once the schema has grown attachments to a
particular database.

Export is lossless: provenance, confirmation state, versions and profile
scoping all survive a round trip. Sensitive fields are included by default
because this is the user's own copy of their own data; ``redact=True`` produces
a shareable version instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from haru.brain.fact_boundary import FactBoundaryOverrides
from haru.brain.models import (
    DEFAULT_PROFILE_ID,
    BrainRecord,
    sensitive_paths,
)
from haru.brain.provenance import utcnow
from haru.brain.store import (
    RECORD_KINDS,
    SINGLETON_KINDS,
    BrainStore,
)

EXPORT_FORMAT = "haru.brain.v1"

_KIND_TO_RECORD = {v: k for k, v in RECORD_KINDS.items()}
_KIND_TO_SINGLETON = {v: k for k, v in SINGLETON_KINDS.items()}

#: Placeholder written in place of sensitive values when redacting.
REDACTED = "[redacted]"


def _redact(payload: dict[str, Any], model: type) -> dict[str, Any]:
    """Blank out fields the schema marks sensitive.

    Uses :func:`sensitive_paths` rather than a hardcoded list, so a new PII
    field is covered the moment it is declared (PRD §13.2).
    """
    out = dict(payload)
    for path in sensitive_paths(model):
        if "." in path:
            continue  # nested blocks are redacted via their own model
        if path in out and out[path] is not None:
            out[path] = [] if isinstance(out[path], list) else REDACTED
    return out


def export_brain(
    store: BrainStore,
    *,
    profile_id: str | None = DEFAULT_PROFILE_ID,
    redact: bool = False,
) -> dict[str, Any]:
    """Serialise a profile — or every profile when ``profile_id`` is None."""
    profiles = [profile_id] if profile_id is not None else list(store.profiles())
    if not profiles:
        profiles = [DEFAULT_PROFILE_ID]

    payload: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "exported_at": utcnow().isoformat(),
        "redacted": redact,
        "profiles": {},
    }

    for pid in profiles:
        records: dict[str, list[dict]] = {}
        for model, kind in RECORD_KINDS.items():
            rows = store.list(model, profile_id=pid)
            if rows:
                records[kind] = [
                    _redact(r.model_dump(mode="json"), model) if redact
                    else r.model_dump(mode="json")
                    for r in rows
                ]

        singletons: dict[str, dict] = {}
        for model, kind in SINGLETON_KINDS.items():
            block = store.get_singleton(model, profile_id=pid)
            if block is not None:
                dumped = block.model_dump(mode="json")
                singletons[kind] = _redact(dumped, model) if redact else dumped

        payload["profiles"][pid] = {"records": records, "singletons": singletons}

    return payload


def write_export(
    store: BrainStore,
    path: Path | str,
    *,
    profile_id: str | None = DEFAULT_PROFILE_ID,
    redact: bool = False,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            export_brain(store, profile_id=profile_id, redact=redact),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return target


class ImportFormatError(ValueError):
    """The payload is not a Haru brain export this version understands."""


def import_brain(
    store: BrainStore, payload: dict[str, Any], *, into_profile: str | None = None
) -> dict[str, int]:
    """Load an export back into a store.

    Refuses redacted exports: they have holes where facts used to be, and
    importing one would silently degrade a Brain.
    """
    fmt = payload.get("format")
    if fmt != EXPORT_FORMAT:
        raise ImportFormatError(f"unsupported export format: {fmt!r}")
    if payload.get("redacted"):
        raise ImportFormatError(
            "refusing to import a redacted export — sensitive values were stripped"
        )

    counts: dict[str, int] = {}
    for pid, block in payload.get("profiles", {}).items():
        target_pid = into_profile or pid

        for kind, rows in block.get("records", {}).items():
            model = _KIND_TO_RECORD.get(kind)
            if model is None:
                raise ImportFormatError(f"unknown record kind: {kind!r}")
            for row in rows:
                record: BrainRecord = model.model_validate({**row, "profile_id": target_pid})
                store.put(record)
                counts[kind] = counts.get(kind, 0) + 1

        for kind, row in block.get("singletons", {}).items():
            model = _KIND_TO_SINGLETON.get(kind)
            if model is None:
                raise ImportFormatError(f"unknown singleton kind: {kind!r}")
            store.put_singleton(
                model.model_validate({**row, "profile_id": target_pid})
            )
            counts[kind] = counts.get(kind, 0) + 1

    return counts


def read_import(
    store: BrainStore, path: Path | str, *, into_profile: str | None = None
) -> dict[str, int]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return import_brain(store, payload, into_profile=into_profile)


__all__ = [
    "EXPORT_FORMAT",
    "REDACTED",
    "FactBoundaryOverrides",
    "ImportFormatError",
    "export_brain",
    "import_brain",
    "read_import",
    "write_export",
]
