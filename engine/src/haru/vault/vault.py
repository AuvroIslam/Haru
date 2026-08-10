"""Encrypted document vault (PRD §7).

Forms don't just ask questions, they demand files: transcripts, passports,
certificates, proof of address. Those are the most sensitive things Haru holds,
so they are encrypted at rest and never uploaded without the user saying so.

Three rules are enforced here rather than left to callers:

1. **Sensitive documents require explicit per-use consent.** Identity documents
   default to ``NEVER_UPLOAD_WITHOUT_ASKING``; :meth:`Vault.open_for_upload`
   refuses them unless ``consent=True`` is passed for that specific use.
2. **Expiry is tracked.** A lapsed passport or certification is worse than a
   missing one, because it looks fine until someone checks.
3. **Credential documents are evidence.** A certificate stored here is what
   makes the matching credential claimable (PRD §10.2).

Key management is deliberately simple for now: a key file beside the vault with
owner-only permissions. Moving it into the OS keychain is a later, contained
change — see ``KEY_FILENAME``.
"""

from __future__ import annotations

import os
import stat
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Iterator

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field

from haru.brain.models import DEFAULT_PROFILE_ID, _new_id
from haru.brain.provenance import Provenance, today, utcnow

KEY_FILENAME = "vault.key"
BLOB_DIRNAME = "blobs"

#: How far ahead to warn about expiry by default.
DEFAULT_EXPIRY_HORIZON = timedelta(days=60)


class DocumentType(str, Enum):
    CV = "cv"
    COVER_LETTER = "cover_letter"
    TRANSCRIPT = "transcript"
    CERTIFICATE = "certificate"
    ID = "id"
    PASSPORT = "passport"
    PHOTO = "photo"
    PORTFOLIO = "portfolio"
    REFERENCE_LETTER = "reference_letter"
    TAX_DOCUMENT = "tax_document"
    PROOF_OF_ADDRESS = "proof_of_address"
    OTHER = "other"


class Sensitivity(str, Enum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    NEVER_UPLOAD_WITHOUT_ASKING = "never_upload_without_asking"


#: Document types that carry identity or financial data. These default to the
#: strictest setting; a user may lower it deliberately but never by accident.
_GUARDED_TYPES: frozenset[DocumentType] = frozenset(
    {
        DocumentType.ID,
        DocumentType.PASSPORT,
        DocumentType.TAX_DOCUMENT,
        DocumentType.PROOF_OF_ADDRESS,
    }
)


def default_sensitivity(doc_type: DocumentType) -> Sensitivity:
    if doc_type in _GUARDED_TYPES:
        return Sensitivity.NEVER_UPLOAD_WITHOUT_ASKING
    if doc_type is DocumentType.TRANSCRIPT:
        return Sensitivity.SENSITIVE
    return Sensitivity.NORMAL


class ConsentRequired(PermissionError):
    """Raised when a guarded document is requested without explicit consent."""


class Document(BaseModel):
    """Metadata for one stored file. The bytes live encrypted on disk."""

    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=_new_id)
    profile_id: str = DEFAULT_PROFILE_ID
    doc_type: DocumentType
    filename: str
    sensitivity: Sensitivity
    provenance: Provenance
    issued_date: date | None = None
    expiry_date: date | None = None
    size_bytes: int = 0
    #: Set when this document evidences a credential (PRD §10.2).
    credential_ref: str | None = None
    created_at: object = Field(default_factory=utcnow)

    @property
    def requires_consent(self) -> bool:
        return self.sensitivity is Sensitivity.NEVER_UPLOAD_WITHOUT_ASKING

    def is_expired(self, on: date | None = None) -> bool:
        if self.expiry_date is None:
            return False
        return self.expiry_date < (on or today())

    def expires_within(
        self, horizon: timedelta = DEFAULT_EXPIRY_HORIZON, on: date | None = None
    ) -> bool:
        """True when expiry is imminent (or already past)."""
        if self.expiry_date is None:
            return False
        return self.expiry_date <= (on or today()) + horizon


def _load_or_create_key(path: Path) -> bytes:
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    path.write_bytes(key)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # owner read/write only
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        pass
    return key


class Vault:
    """Encrypted storage for the user's documents."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.blobs = self.root / BLOB_DIRNAME
        self.blobs.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(_load_or_create_key(self.root / KEY_FILENAME))
        self._documents: dict[str, Document] = {}

    # ── writing ──────────────────────────────────────────────────────────

    def add(
        self,
        content: bytes,
        *,
        doc_type: DocumentType,
        filename: str,
        provenance: Provenance,
        profile_id: str = DEFAULT_PROFILE_ID,
        sensitivity: Sensitivity | None = None,
        issued_date: date | None = None,
        expiry_date: date | None = None,
        credential_ref: str | None = None,
    ) -> Document:
        """Encrypt and store a file, returning its metadata."""
        doc = Document(
            profile_id=profile_id,
            doc_type=doc_type,
            filename=filename,
            sensitivity=sensitivity or default_sensitivity(doc_type),
            provenance=provenance,
            issued_date=issued_date,
            expiry_date=expiry_date,
            size_bytes=len(content),
            credential_ref=credential_ref,
        )
        self._blob_path(doc.id).write_bytes(self._fernet.encrypt(content))
        self._documents[doc.id] = doc
        return doc

    def add_file(self, path: Path | str, **kwargs) -> Document:
        source = Path(path)
        kwargs.setdefault("filename", source.name)
        return self.add(source.read_bytes(), **kwargs)

    # ── reading ──────────────────────────────────────────────────────────

    def read(self, doc_id: str) -> bytes:
        """Decrypt a document for Haru's own use (parsing, display)."""
        path = self._blob_path(doc_id)
        if not path.exists():
            raise FileNotFoundError(f"no document {doc_id!r} in vault")
        try:
            return self._fernet.decrypt(path.read_bytes())
        except InvalidToken as exc:
            raise InvalidToken(
                f"document {doc_id!r} could not be decrypted — wrong or rotated key"
            ) from exc

    def open_for_upload(self, doc_id: str, *, consent: bool = False) -> bytes:
        """Read a document that is about to be sent to a third party.

        Guarded documents require ``consent=True`` for this specific use. A
        blanket setting is not sufficient — PRD §7 requires explicit per-use
        consent, because "I once allowed my passport" must not mean "always".
        """
        doc = self.get(doc_id)
        if doc is None:
            raise FileNotFoundError(f"no document {doc_id!r} in vault")
        if doc.requires_consent and not consent:
            raise ConsentRequired(
                f"{doc.filename} ({doc.doc_type.value}) needs explicit consent "
                f"before it can be uploaded"
            )
        return self.read(doc_id)

    def get(self, doc_id: str) -> Document | None:
        return self._documents.get(doc_id)

    def list(
        self,
        *,
        profile_id: str = DEFAULT_PROFILE_ID,
        doc_type: DocumentType | None = None,
    ) -> list[Document]:
        return [
            d
            for d in self._documents.values()
            if d.profile_id == profile_id
            and (doc_type is None or d.doc_type is doc_type)
        ]

    def delete(self, doc_id: str) -> bool:
        doc = self._documents.pop(doc_id, None)
        if doc is None:
            return False
        self._blob_path(doc_id).unlink(missing_ok=True)
        return True

    # ── expiry ───────────────────────────────────────────────────────────

    def expiring(
        self,
        *,
        profile_id: str = DEFAULT_PROFILE_ID,
        horizon: timedelta = DEFAULT_EXPIRY_HORIZON,
        on: date | None = None,
    ) -> list[Document]:
        """Documents already expired or expiring within the horizon, soonest first."""
        due = [
            d
            for d in self.list(profile_id=profile_id)
            if d.expires_within(horizon, on=on)
        ]
        return sorted(due, key=lambda d: d.expiry_date or date.max)

    def expired(
        self, *, profile_id: str = DEFAULT_PROFILE_ID, on: date | None = None
    ) -> list[Document]:
        return [d for d in self.list(profile_id=profile_id) if d.is_expired(on)]

    # ── internals ────────────────────────────────────────────────────────

    def _blob_path(self, doc_id: str) -> Path:
        return self.blobs / f"{doc_id}.enc"

    def __iter__(self) -> Iterator[Document]:
        return iter(self._documents.values())

    def __len__(self) -> int:
        return len(self._documents)
