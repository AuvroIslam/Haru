"""Stripping personal data before anything leaves the machine (PRD §13.2).

Which fields count as sensitive is not a list maintained here — it is read from
the Brain schema itself via
:func:`~haru.brain.models.sensitive_paths`. A field marked sensitive when it is
declared is covered automatically, so adding one later cannot silently create a
leak.

Two things are scrubbed:

* **Declared PII** — date of birth, national IDs, voluntary disclosures,
  salary history: every field the schema marks.
* **Pattern matches** — anything shaped like an email, phone number, or long
  digit string, wherever it appears. Prose assembled from Brain facts can carry
  a phone number that no structured field is responsible for.

Longest values are replaced first, so a substring cannot survive by being
scrubbed after the string that contains it.
"""

from __future__ import annotations

import re

from haru.brain.models import (
    DEFAULT_PROFILE_ID,
    Compensation,
    Identity,
    StandardAnswers,
    VoluntaryDisclosure,
    WorkAuthorization,
    sensitive_paths,
)
from haru.brain.store import BrainStore
from haru.models.types import Redacted

#: Set on every Redacted this module produces. Cloud providers check for it.
MARKER = "haru.redacted.v1"

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?){2,4}\d{2,4}(?!\w)")),
    ("ID", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("LONGNUM", re.compile(r"\b\d{9,}\b")),
)

#: Blocks whose sensitive fields are collected from the Brain.
_BLOCKS = (Identity, Compensation, VoluntaryDisclosure, StandardAnswers, WorkAuthorization)


def _values_from(block, model) -> list[str]:
    """Pull the string values of every field the schema marks sensitive."""
    found: list[str] = []
    for path in sensitive_paths(model):
        if "." in path:
            continue
        value = getattr(block, path, None)
        if value is None:
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            # Attested values wrap the real one.
            raw = getattr(item, "value", item)
            if raw is not None and str(raw).strip():
                found.append(str(raw))
    return found


def sensitive_values(
    store: BrainStore, *, profile_id: str = DEFAULT_PROFILE_ID
) -> list[str]:
    """Every value in this Brain that must never leave the machine."""
    values: list[str] = []
    for model in _BLOCKS:
        block = store.get_singleton(model, profile_id=profile_id)
        if block is not None:
            values.extend(_values_from(block, model))

    identity = store.get_singleton(Identity, profile_id=profile_id)
    if identity is not None:
        # Two different bars are in play. The schema's `sensitive` marker means
        # "never auto-fill, never share casually" — a name fails that test,
        # since it is printed on the CV. The bar for leaving the machine is
        # broader: PRD §13.2 says *identity* does not reach a cloud model, and
        # a name plus an address is identifying even when each looks harmless.
        for attested in list(identity.emails) + list(identity.phones):
            values.append(str(attested.value))
        for field in (
            identity.legal_name,
            identity.preferred_name,
            identity.street,
            identity.postal_code,
        ):
            if field is not None:
                values.append(str(field.value))
        for link in identity.links:
            values.append(link.url)

    return [v for v in values if len(v) >= 3]


def redact(text: str, values: list[str] | None = None) -> Redacted:
    """Remove known values and PII-shaped patterns from ``text``."""
    removed: dict[str, str] = {}
    result = text
    counter = 0

    # Longest first: scrubbing "Ada" before "Ada Lovelace" would leave a
    # half-redacted name behind.
    for value in sorted(set(values or []), key=len, reverse=True):
        if value and value in result:
            counter += 1
            placeholder = f"[REDACTED_{counter}]"
            removed[placeholder] = value
            result = result.replace(value, placeholder)

    for label, pattern in _PATTERNS:
        def _swap(match: re.Match[str]) -> str:
            nonlocal counter
            counter += 1
            placeholder = f"[{label}_{counter}]"
            removed[placeholder] = match.group(0)
            return placeholder

        result = pattern.sub(_swap, result)

    return Redacted(text=result, removed=removed, marker=MARKER)


def redact_for(
    text: str, store: BrainStore, *, profile_id: str = DEFAULT_PROFILE_ID
) -> Redacted:
    """Redact using this Brain's sensitive values."""
    return redact(text, sensitive_values(store, profile_id=profile_id))


def is_redacted(payload: object) -> bool:
    return isinstance(payload, Redacted) and payload.marker == MARKER
