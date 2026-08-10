"""The validation seam (PRD §17.1).

Every generation path calls :func:`validate` from day one. Until M3 the active
validator is a stub that passes everything and records what it saw. When the
real validator lands it is installed here and no call site changes.

The observation log is the point of the stub. It captures what generation
actually produced during M1–M2, which is better evidence for building the
detectors than guessing at them in advance.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

from haru.brain.fact_boundary import FactBoundary
from haru.brain.provenance import utcnow
from haru.validation.types import (
    Artifact,
    Result,
    ValidationMode,
)

log = logging.getLogger(__name__)


@runtime_checkable
class Validator(Protocol):
    """Anything that can judge an artifact against a fact boundary."""

    def validate(
        self,
        artifact: Artifact,
        boundary: FactBoundary,
        mode: ValidationMode = ValidationMode.NORMAL,
    ) -> Result: ...


class ObservationLog:
    """Append-only JSONL record of everything the seam has seen."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self.observations: list[dict] = []

    def record(
        self, artifact: Artifact, boundary: FactBoundary, mode: ValidationMode
    ) -> None:
        entry = {
            "at": utcnow().isoformat(),
            "kind": artifact.kind.value,
            "mode": mode.value,
            "profile_id": artifact.profile_id,
            "text_length": len(artifact.text),
            "text": artifact.text,
            "context": artifact.context,
            "boundary_empty": boundary.is_empty,
            "boundary_sizes": {
                "skills": len(boundary.allowed_skills),
                "orgs": len(boundary.preserved_orgs),
                "projects": len(boundary.preserved_projects),
                "institutions": len(boundary.preserved_institutions),
                "credentials": len(boundary.claimable_credentials),
                "metrics": len(boundary.real_metrics),
            },
        }
        with self._lock:
            self.observations.append(entry)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")

    def clear(self) -> None:
        with self._lock:
            self.observations.clear()


class PassThroughValidator:
    """M0 stub. Records the artifact and approves it.

    This is deliberately permissive and deliberately loud: it warns once per
    process so a stubbed validator can never be mistaken for a real one in a
    running system.
    """

    def __init__(self, observation_log: ObservationLog | None = None) -> None:
        self.log = observation_log or ObservationLog()
        self._warned = False

    def validate(
        self,
        artifact: Artifact,
        boundary: FactBoundary,
        mode: ValidationMode = ValidationMode.NORMAL,
    ) -> Result:
        if not self._warned:
            log.warning(
                "Validation is STUBBED (M0). Generated text is not being checked "
                "against the fact boundary. This must not reach a real submission "
                "— see PRD §17.1."
            )
            self._warned = True
        self.log.record(artifact, boundary, mode)
        return Result(artifact=artifact, mode=mode, violations=(), stubbed=True)


_active: Validator = PassThroughValidator()
_active_lock = threading.Lock()


def get_validator() -> Validator:
    return _active


def set_validator(validator: Validator) -> Validator:
    """Install a validator. M3 calls this once at startup; tests use it freely."""
    global _active
    with _active_lock:
        previous, _active = _active, validator
    return previous


def reset_validator() -> None:
    set_validator(PassThroughValidator())


def validate(
    artifact: Artifact,
    boundary: FactBoundary,
    mode: ValidationMode = ValidationMode.NORMAL,
) -> Result:
    """The single entry point every generation path must call.

    Keeping this a module-level function rather than an injected dependency is
    what makes M3 a drop-in: the detectors change, the call sites do not.
    """
    return _active.validate(artifact, boundary, mode)


def is_stubbed() -> bool:
    """True while the pass-through stub is installed.

    Submission paths should refuse to send anything in the user's name while
    this is true (PRD §17.1: M3 ships before M4).
    """
    return isinstance(_active, PassThroughValidator)
