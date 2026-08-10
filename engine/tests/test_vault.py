"""Tests for the encrypted document vault (PRD §7)."""

from datetime import date, timedelta

import pytest
from cryptography.fernet import Fernet

from haru.brain.provenance import Provenance, Source
from haru.vault.vault import (
    KEY_FILENAME,
    ConsentRequired,
    DocumentType,
    Sensitivity,
    Vault,
    default_sensitivity,
)

CONTENT = b"%PDF-1.4 pretend this is a passport scan"


@pytest.fixture
def vault(tmp_path):
    return Vault(tmp_path / "vault")


def entered() -> Provenance:
    return Provenance.entered()


class TestEncryption:
    def test_plaintext_is_not_on_disk(self, vault, tmp_path):
        vault.add(
            CONTENT,
            doc_type=DocumentType.PASSPORT,
            filename="passport.pdf",
            provenance=entered(),
        )
        for path in (tmp_path / "vault" / "blobs").iterdir():
            assert CONTENT not in path.read_bytes()

    def test_round_trip(self, vault):
        doc = vault.add(
            CONTENT,
            doc_type=DocumentType.CV,
            filename="cv.pdf",
            provenance=entered(),
        )
        assert vault.read(doc.id) == CONTENT

    def test_key_is_created_once_and_reused(self, tmp_path):
        v1 = Vault(tmp_path / "vault")
        key = (tmp_path / "vault" / KEY_FILENAME).read_bytes()
        doc = v1.add(
            CONTENT, doc_type=DocumentType.CV, filename="cv.pdf", provenance=entered()
        )

        v2 = Vault(tmp_path / "vault")
        assert (tmp_path / "vault" / KEY_FILENAME).read_bytes() == key
        assert v2.read(doc.id) == CONTENT

    def test_wrong_key_cannot_decrypt(self, tmp_path):
        v1 = Vault(tmp_path / "vault")
        doc = v1.add(
            CONTENT, doc_type=DocumentType.CV, filename="cv.pdf", provenance=entered()
        )
        (tmp_path / "vault" / KEY_FILENAME).write_bytes(Fernet.generate_key())

        v2 = Vault(tmp_path / "vault")
        with pytest.raises(Exception):
            v2.read(doc.id)

    def test_missing_document(self, vault):
        with pytest.raises(FileNotFoundError):
            vault.read("nope")


class TestConsent:
    """PRD §7 — sensitive documents need explicit per-use consent."""

    @pytest.mark.parametrize(
        "doc_type",
        [
            DocumentType.ID,
            DocumentType.PASSPORT,
            DocumentType.TAX_DOCUMENT,
            DocumentType.PROOF_OF_ADDRESS,
        ],
    )
    def test_identity_documents_are_guarded_by_default(self, doc_type):
        assert default_sensitivity(doc_type) is Sensitivity.NEVER_UPLOAD_WITHOUT_ASKING

    def test_cv_is_not_guarded(self):
        assert default_sensitivity(DocumentType.CV) is Sensitivity.NORMAL

    def test_upload_without_consent_is_refused(self, vault):
        doc = vault.add(
            CONTENT,
            doc_type=DocumentType.PASSPORT,
            filename="passport.pdf",
            provenance=entered(),
        )
        with pytest.raises(ConsentRequired, match="passport"):
            vault.open_for_upload(doc.id)

    def test_upload_with_consent_succeeds(self, vault):
        doc = vault.add(
            CONTENT,
            doc_type=DocumentType.PASSPORT,
            filename="passport.pdf",
            provenance=entered(),
        )
        assert vault.open_for_upload(doc.id, consent=True) == CONTENT

    def test_consent_is_per_use_not_remembered(self, vault):
        doc = vault.add(
            CONTENT,
            doc_type=DocumentType.PASSPORT,
            filename="passport.pdf",
            provenance=entered(),
        )
        vault.open_for_upload(doc.id, consent=True)
        with pytest.raises(ConsentRequired):
            vault.open_for_upload(doc.id)

    def test_ordinary_documents_upload_freely(self, vault):
        doc = vault.add(
            CONTENT, doc_type=DocumentType.CV, filename="cv.pdf", provenance=entered()
        )
        assert vault.open_for_upload(doc.id) == CONTENT

    def test_internal_read_bypasses_consent(self, vault):
        # Haru must be able to parse a passport to extract fields; that is not
        # the same as sending it to a third party.
        doc = vault.add(
            CONTENT,
            doc_type=DocumentType.PASSPORT,
            filename="passport.pdf",
            provenance=entered(),
        )
        assert vault.read(doc.id) == CONTENT

    def test_sensitivity_can_be_set_explicitly(self, vault):
        doc = vault.add(
            CONTENT,
            doc_type=DocumentType.CV,
            filename="cv.pdf",
            provenance=entered(),
            sensitivity=Sensitivity.NEVER_UPLOAD_WITHOUT_ASKING,
        )
        with pytest.raises(ConsentRequired):
            vault.open_for_upload(doc.id)


class TestExpiry:
    def _doc(self, vault, days: int, name: str = "doc.pdf"):
        return vault.add(
            CONTENT,
            doc_type=DocumentType.CERTIFICATE,
            filename=name,
            provenance=entered(),
            expiry_date=date.today() + timedelta(days=days),
        )

    def test_expired_document(self, vault):
        doc = self._doc(vault, -1)
        assert doc.is_expired()
        assert doc in vault.expired()

    def test_valid_document(self, vault):
        doc = self._doc(vault, 365)
        assert not doc.is_expired()
        assert vault.expired() == []

    def test_no_expiry_never_expires(self, vault):
        doc = vault.add(
            CONTENT, doc_type=DocumentType.CV, filename="cv.pdf", provenance=entered()
        )
        assert not doc.is_expired()
        assert not doc.expires_within()

    def test_expiring_soon_is_surfaced(self, vault):
        soon = self._doc(vault, 30, "soon.pdf")
        assert soon in vault.expiring()

    def test_distant_expiry_is_not_surfaced(self, vault):
        far = self._doc(vault, 365, "far.pdf")
        assert far not in vault.expiring()

    def test_expiring_includes_already_expired(self, vault):
        past = self._doc(vault, -5, "past.pdf")
        assert past in vault.expiring()

    def test_expiring_sorts_soonest_first(self, vault):
        self._doc(vault, 50, "later.pdf")
        self._doc(vault, 5, "sooner.pdf")
        assert [d.filename for d in vault.expiring()] == ["sooner.pdf", "later.pdf"]

    def test_custom_horizon(self, vault):
        doc = self._doc(vault, 100)
        assert doc not in vault.expiring()
        assert doc in vault.expiring(horizon=timedelta(days=200))

    def test_reference_date(self, vault):
        doc = vault.add(
            CONTENT,
            doc_type=DocumentType.PASSPORT,
            filename="p.pdf",
            provenance=entered(),
            expiry_date=date(2030, 1, 1),
        )
        assert doc.is_expired(date(2031, 1, 1))
        assert not doc.is_expired(date(2029, 1, 1))


class TestManagement:
    def test_list_and_filter(self, vault):
        vault.add(CONTENT, doc_type=DocumentType.CV, filename="cv.pdf", provenance=entered())
        vault.add(
            CONTENT,
            doc_type=DocumentType.CERTIFICATE,
            filename="cert.pdf",
            provenance=entered(),
        )
        assert len(vault.list()) == 2
        assert len(vault.list(doc_type=DocumentType.CV)) == 1

    def test_profile_scoping(self, vault):
        vault.add(
            CONTENT,
            doc_type=DocumentType.CV,
            filename="a.pdf",
            provenance=entered(),
            profile_id="academic",
        )
        assert len(vault.list(profile_id="academic")) == 1
        assert vault.list(profile_id="default") == []

    def test_delete_removes_blob(self, vault, tmp_path):
        doc = vault.add(
            CONTENT, doc_type=DocumentType.CV, filename="cv.pdf", provenance=entered()
        )
        assert vault.delete(doc.id)
        assert vault.get(doc.id) is None
        assert not (tmp_path / "vault" / "blobs" / f"{doc.id}.enc").exists()
        assert not vault.delete(doc.id)

    def test_add_file_from_disk(self, vault, tmp_path):
        source = tmp_path / "resume.pdf"
        source.write_bytes(CONTENT)
        doc = vault.add_file(
            source, doc_type=DocumentType.CV, provenance=entered()
        )
        assert doc.filename == "resume.pdf"
        assert vault.read(doc.id) == CONTENT

    def test_records_size(self, vault):
        doc = vault.add(
            CONTENT, doc_type=DocumentType.CV, filename="cv.pdf", provenance=entered()
        )
        assert doc.size_bytes == len(CONTENT)

    def test_credential_evidence_link(self, vault):
        doc = vault.add(
            CONTENT,
            doc_type=DocumentType.CERTIFICATE,
            filename="aws.pdf",
            provenance=Provenance.create(Source.DOCUMENT_EXTRACTION),
            credential_ref="cred-1",
        )
        assert doc.credential_ref == "cred-1"

    def test_len_and_iteration(self, vault):
        vault.add(CONTENT, doc_type=DocumentType.CV, filename="a.pdf", provenance=entered())
        vault.add(CONTENT, doc_type=DocumentType.CV, filename="b.pdf", provenance=entered())
        assert len(vault) == 2
        assert {d.filename for d in vault} == {"a.pdf", "b.pdf"}
