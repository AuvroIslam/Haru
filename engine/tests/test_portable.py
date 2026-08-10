"""Tests for Brain export/import (PRD P2 — the user owns the record)."""

import json

import pytest

from haru.brain.fact_boundary import derive
from haru.brain.models import (
    Compensation,
    Credential,
    Experience,
    Identity,
    Preferences,
    Project,
    Skill,
    Tone,
    VoluntaryDisclosure,
)
from haru.brain.portable import (
    EXPORT_FORMAT,
    REDACTED,
    ImportFormatError,
    export_brain,
    import_brain,
    read_import,
    write_export,
)
from haru.brain.provenance import Attested, Provenance, Source
from haru.brain.store import BrainStore


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "a.sqlite")
    yield s
    s.close()


@pytest.fixture
def other(tmp_path):
    s = BrainStore(tmp_path / "b.sqlite")
    yield s
    s.close()


def imported() -> Provenance:
    return Provenance.create(Source.CV_IMPORT)


def confirmed() -> Provenance:
    return Provenance.entered()


def populate(store: BrainStore) -> None:
    store.put(Project(name="Haru", provenance=confirmed(), technologies=["Python"]))
    store.put(Experience(org="Northwind", title="Engineer", provenance=confirmed()))
    store.put(Skill(name="Python", provenance=confirmed(), evidence_refs=["e1"]))
    store.put(Credential(name="AWS CP", provenance=confirmed(), document_ref="d1"))
    store.put(Project(name="Pending", provenance=imported()))
    store.put_singleton(Identity(legal_name=Attested.entered("Ada Lovelace")))
    store.put_singleton(Preferences(tone=Tone.WARM))


class TestExport:
    def test_has_format_marker(self, store):
        assert export_brain(store)["format"] == EXPORT_FORMAT

    def test_includes_records_by_kind(self, store):
        populate(store)
        records = export_brain(store)["profiles"]["default"]["records"]
        assert {p["name"] for p in records["project"]} == {"Haru", "Pending"}
        assert records["credential"][0]["name"] == "AWS CP"

    def test_includes_singletons(self, store):
        populate(store)
        singles = export_brain(store)["profiles"]["default"]["singletons"]
        assert singles["identity"]["legal_name"]["value"] == "Ada Lovelace"
        assert singles["preferences"]["tone"] == "warm"

    def test_omits_empty_kinds(self, store):
        store.put(Project(name="Haru", provenance=confirmed()))
        records = export_brain(store)["profiles"]["default"]["records"]
        assert "credential" not in records

    def test_empty_brain_exports_cleanly(self, store):
        payload = export_brain(store)
        assert payload["profiles"]["default"] == {"records": {}, "singletons": {}}

    def test_all_profiles(self, store):
        store.put(Project(name="a", provenance=confirmed(), profile_id="academic"))
        store.put(Project(name="i", provenance=confirmed(), profile_id="industry"))
        payload = export_brain(store, profile_id=None)
        assert set(payload["profiles"]) == {"academic", "industry"}

    def test_writes_readable_json(self, store, tmp_path):
        populate(store)
        path = write_export(store, tmp_path / "out" / "brain.json")
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["format"] == EXPORT_FORMAT


class TestRoundTrip:
    def test_records_survive(self, store, other):
        populate(store)
        import_brain(other, export_brain(store))
        assert {p.name for p in other.list(Project)} == {"Haru", "Pending"}

    def test_provenance_survives(self, store, other):
        store.put(Project(name="Haru", provenance=imported()))
        import_brain(other, export_brain(store))
        restored = other.list(Project)[0]
        assert restored.provenance.source is Source.CV_IMPORT
        assert not restored.provenance.confirmed

    def test_confirmation_state_survives(self, store, other):
        populate(store)
        import_brain(other, export_brain(store))
        confirmed_names = {p.name for p in other.list(Project, confirmed_only=True)}
        assert confirmed_names == {"Haru"}, "unconfirmed must not arrive confirmed"

    def test_fact_boundary_is_reproduced(self, store, other):
        populate(store)
        import_brain(other, export_brain(store))

        original, restored = derive(store), derive(other)
        assert restored.allowed_skills == original.allowed_skills
        assert restored.preserved_orgs == original.preserved_orgs
        assert restored.claimable_credentials == original.claimable_credentials

    def test_ids_are_preserved(self, store, other):
        p = store.put(Project(name="Haru", provenance=confirmed()))
        import_brain(other, export_brain(store))
        assert other.get(Project, p.id) is not None

    def test_singletons_survive(self, store, other):
        populate(store)
        import_brain(other, export_brain(store))
        assert other.get_singleton(Identity).legal_name.value == "Ada Lovelace"
        assert other.get_singleton(Preferences).tone is Tone.WARM

    def test_nested_values_survive(self, store, other):
        store.put(
            Experience(
                org="Acme",
                title="Dev",
                provenance=confirmed(),
                achievements=[{"text": "Sped up", "metric": "40%", "verified": True}],
            )
        )
        import_brain(other, export_brain(store))
        ach = other.list(Experience)[0].achievements[0]
        assert ach.metric == "40%"
        assert ach.verified

    def test_file_round_trip(self, store, other, tmp_path):
        populate(store)
        path = write_export(store, tmp_path / "brain.json")
        counts = read_import(other, path)
        assert counts["project"] == 2

    def test_import_into_a_different_profile(self, store, other):
        store.put(Project(name="Haru", provenance=confirmed()))
        import_brain(other, export_brain(store), into_profile="academic")
        assert other.list(Project, profile_id="academic")
        assert not other.list(Project, profile_id="default")


class TestRedaction:
    def test_sensitive_singleton_fields_are_stripped(self, store):
        store.put_singleton(Compensation(expectation=90000, current_salary=70000))
        singles = export_brain(store, redact=True)["profiles"]["default"]["singletons"]
        assert singles["compensation"]["current_salary"] == REDACTED
        assert singles["compensation"]["expectation"] == 90000

    def test_disclosures_are_stripped(self, store):
        store.put_singleton(VoluntaryDisclosure(gender="woman"))
        singles = export_brain(store, redact=True)["profiles"]["default"]["singletons"]
        assert singles["voluntary_disclosure"]["gender"] == REDACTED

    def test_identity_pii_is_stripped(self, store):
        store.put_singleton(
            Identity(
                legal_name=Attested.entered("Ada"),
                national_ids=[Attested.entered("123-45-6789")],
            )
        )
        singles = export_brain(store, redact=True)["profiles"]["default"]["singletons"]
        assert singles["identity"]["national_ids"] == []
        assert singles["identity"]["legal_name"]["value"] == "Ada", "name is not PII-marked"

    def test_unredacted_export_keeps_everything(self, store):
        store.put_singleton(Compensation(current_salary=70000))
        singles = export_brain(store)["profiles"]["default"]["singletons"]
        assert singles["compensation"]["current_salary"] == 70000

    def test_export_is_flagged_as_redacted(self, store):
        assert export_brain(store, redact=True)["redacted"] is True
        assert export_brain(store)["redacted"] is False


class TestImportValidation:
    def test_rejects_unknown_format(self, store):
        with pytest.raises(ImportFormatError, match="format"):
            import_brain(store, {"format": "someone-elses-tool.v9"})

    def test_rejects_missing_format(self, store):
        with pytest.raises(ImportFormatError):
            import_brain(store, {"profiles": {}})

    def test_refuses_redacted_exports(self, store, other):
        store.put_singleton(Compensation(current_salary=70000))
        with pytest.raises(ImportFormatError, match="redacted"):
            import_brain(other, export_brain(store, redact=True))

    def test_rejects_unknown_record_kind(self, store):
        payload = {
            "format": EXPORT_FORMAT,
            "profiles": {"default": {"records": {"spaceship": [{}]}, "singletons": {}}},
        }
        with pytest.raises(ImportFormatError, match="spaceship"):
            import_brain(store, payload)

    def test_reports_counts(self, store, other):
        populate(store)
        counts = import_brain(other, export_brain(store))
        assert counts["project"] == 2
        assert counts["identity"] == 1
