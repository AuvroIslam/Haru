"""Tests for the Brain schema (PRD §6.2).

These concentrate on the invariants that carry safety weight — claimability of
credentials, evidence on skills, disclosure defaults, and the machine-readable
sensitivity marking the redaction layer will depend on.
"""

from datetime import date, timedelta

from pydantic import BaseModel

from haru.brain.models import (
    DECLINE,
    DEFAULT_PROFILE_ID,
    Achievement,
    Compensation,
    Credential,
    Experience,
    Identity,
    Preferences,
    Project,
    Skill,
    StandardAnswers,
    VoluntaryDisclosure,
    sensitive_paths,
)
from haru.brain.provenance import Attested, Provenance, Source, utcnow


def imported() -> Provenance:
    return Provenance.create(Source.CV_IMPORT, detail="cv.pdf")


def confirmed() -> Provenance:
    return Provenance.entered()


class TestCredentialClaimability:
    """PRD §10.2: certifications are never stretchable."""

    def test_unconfirmed_without_document_is_not_claimable(self):
        c = Credential(name="AWS Solutions Architect", provenance=imported())
        assert not c.is_claimable

    def test_confirmed_without_document_is_not_claimable(self):
        c = Credential(name="AWS Solutions Architect", provenance=confirmed())
        assert not c.is_claimable, "a document is required, not just confirmation"

    def test_document_without_confirmation_is_not_claimable(self):
        c = Credential(
            name="AWS Solutions Architect",
            provenance=imported(),
            document_ref="doc-1",
        )
        assert not c.is_claimable

    def test_confirmed_with_document_is_claimable(self):
        c = Credential(
            name="AWS Solutions Architect",
            provenance=confirmed(),
            document_ref="doc-1",
        )
        assert c.is_claimable

    def test_expiry(self):
        today = utcnow().date()
        past = Credential(
            name="Old", provenance=confirmed(), expiry_date=today - timedelta(days=1)
        )
        future = Credential(
            name="New", provenance=confirmed(), expiry_date=today + timedelta(days=1)
        )
        never = Credential(name="Perpetual", provenance=confirmed())
        assert past.is_expired()
        assert not future.is_expired()
        assert not never.is_expired()

    def test_expiry_accepts_reference_date(self):
        c = Credential(
            name="X", provenance=confirmed(), expiry_date=date(2020, 1, 1)
        )
        assert c.is_expired(date(2021, 1, 1))
        assert not c.is_expired(date(2019, 1, 1))


class TestSkillEvidence:
    """PRD §10.2: a skill with no evidence cannot widen the fact boundary."""

    def test_skill_without_evidence(self):
        assert not Skill(name="Rust", provenance=confirmed()).has_evidence

    def test_skill_with_evidence(self):
        s = Skill(name="Python", provenance=confirmed(), evidence_refs=["proj-1"])
        assert s.has_evidence


class TestRecordEnvelope:
    def test_records_get_distinct_ids(self):
        a = Project(name="A", provenance=imported())
        b = Project(name="B", provenance=imported())
        assert a.id != b.id

    def test_default_profile_id(self):
        assert Project(name="A", provenance=imported()).profile_id == DEFAULT_PROFILE_ID

    def test_is_confirmed_reflects_provenance(self):
        assert not Project(name="A", provenance=imported()).is_confirmed
        assert Project(name="A", provenance=confirmed()).is_confirmed

    def test_version_starts_at_one(self):
        assert Experience(org="Acme", title="Dev", provenance=imported()).version == 1


class TestSafetyDefaults:
    """PRD §16.3: protected characteristics decline by default."""

    def test_voluntary_disclosure_declines_everything(self):
        v = VoluntaryDisclosure()
        assert v.gender == DECLINE
        assert v.race_ethnicity == DECLINE
        assert v.veteran_status == DECLINE
        assert v.disability_status == DECLINE

    def test_current_salary_blank_by_default(self):
        assert Compensation().current_salary is None

    def test_pacing_off_by_default(self):
        p = Preferences().pacing
        assert p.max_per_day is None
        assert p.min_seconds_between_submissions is None

    def test_achievement_metric_unverified_by_default(self):
        assert not Achievement(text="Cut latency", metric="10x").verified


class TestSensitivityMarking:
    """PRD §13.2: the redaction layer enumerates these rather than hardcoding."""

    def test_identity_pii_is_marked(self):
        paths = sensitive_paths(Identity)
        assert "date_of_birth" in paths
        assert "national_ids" in paths

    def test_non_pii_is_not_marked(self):
        paths = sensitive_paths(Identity)
        assert "legal_name" not in paths
        assert "city" not in paths

    def test_every_disclosure_field_is_marked(self):
        assert set(sensitive_paths(VoluntaryDisclosure)) == {
            "gender",
            "race_ethnicity",
            "veteran_status",
            "disability_status",
        }

    def test_compensation_and_standard_answers(self):
        assert sensitive_paths(Compensation) == ["current_salary"]
        assert sensitive_paths(StandardAnswers) == ["criminal_record"]

    def test_nested_models_are_traversed(self):
        class Wrapper(BaseModel):
            identity: Identity
            comp: Compensation

        paths = sensitive_paths(Wrapper)
        assert "identity.date_of_birth" in paths
        assert "identity.national_ids" in paths
        assert "comp.current_salary" in paths


class TestAttestedFields:
    def test_identity_fields_carry_their_own_provenance(self):
        ident = Identity(
            legal_name=Attested.imported("Ada Lovelace", Source.CV_IMPORT),
            city=Attested.entered("London"),
        )
        assert not ident.legal_name.is_confirmed
        assert ident.city.is_confirmed

    def test_confirming_one_field_leaves_others_alone(self):
        ident = Identity(
            legal_name=Attested.imported("Ada", Source.CV_IMPORT),
            city=Attested.imported("London", Source.CV_IMPORT),
        )
        ident.legal_name = ident.legal_name.confirm()
        assert ident.legal_name.is_confirmed
        assert not ident.city.is_confirmed
