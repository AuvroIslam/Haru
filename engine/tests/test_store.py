"""Tests for Brain persistence."""

import pytest

from haru.brain.models import (
    Compensation,
    Credential,
    Experience,
    Identity,
    Preferences,
    Project,
    Skill,
    Tone,
)
from haru.brain.provenance import Attested, Provenance, Source
from haru.brain.store import BrainStore, UnknownKindError, record_kind


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "brain.sqlite")
    yield s
    s.close()


def imported() -> Provenance:
    return Provenance.create(Source.CV_IMPORT, detail="cv.pdf")


def confirmed() -> Provenance:
    return Provenance.entered()


class TestRoundTrip:
    def test_put_and_get(self, store):
        p = store.put(Project(name="Haru", provenance=imported()))
        got = store.get(Project, p.id)
        assert got is not None
        assert got.name == "Haru"
        assert got.provenance.source is Source.CV_IMPORT

    def test_get_missing_returns_none(self, store):
        assert store.get(Project, "nope") is None

    def test_get_is_kind_scoped(self, store):
        p = store.put(Project(name="Haru", provenance=imported()))
        # Same id, wrong kind — must not resolve.
        assert store.get(Skill, p.id) is None

    def test_list_orders_by_creation(self, store):
        store.put_many(
            [
                Project(name="one", provenance=imported()),
                Project(name="two", provenance=imported()),
            ]
        )
        assert [p.name for p in store.list(Project)] == ["one", "two"]

    def test_delete(self, store):
        p = store.put(Project(name="Haru", provenance=imported()))
        assert store.delete(Project, p.id)
        assert store.get(Project, p.id) is None
        assert not store.delete(Project, p.id)

    def test_nested_structures_survive(self, store):
        e = store.put(
            Experience(
                org="Acme",
                title="Engineer",
                provenance=imported(),
                achievements=[
                    {"text": "Cut latency", "metric": "10x", "verified": True}
                ],
            )
        )
        got = store.get(Experience, e.id)
        assert got.achievements[0].metric == "10x"
        assert got.achievements[0].verified


class TestConfirmedFiltering:
    """PRD §6.3 — unconfirmed facts must never widen the fact boundary."""

    def test_confirmed_only_excludes_imports(self, store):
        store.put(Skill(name="Python", provenance=confirmed()))
        store.put(Skill(name="Rust", provenance=imported()))

        assert len(store.list(Skill)) == 2
        names = [s.name for s in store.list(Skill, confirmed_only=True)]
        assert names == ["Python"]

    def test_unconfirmed_queue_sorts_least_confident_first(self, store):
        store.put(Skill(name="mid", provenance=Provenance.create(Source.CV_IMPORT)))
        store.put(Skill(name="low", provenance=Provenance.create(Source.INFERRED)))
        store.put(
            Skill(
                name="high",
                provenance=Provenance.create(Source.DOCUMENT_EXTRACTION),
            )
        )
        assert [r.name for r in store.unconfirmed()] == ["low", "mid", "high"]

    def test_unconfirmed_excludes_confirmed(self, store):
        store.put(Project(name="confirmed", provenance=confirmed()))
        store.put(Project(name="pending", provenance=imported()))
        assert [r.name for r in store.unconfirmed()] == ["pending"]

    def test_unconfirmed_spans_kinds(self, store):
        store.put(Project(name="proj", provenance=imported()))
        store.put(Skill(name="skill", provenance=imported()))
        kinds = {type(r) for r in store.unconfirmed()}
        assert kinds == {Project, Skill}

    def test_unconfirmed_respects_limit(self, store):
        store.put_many(
            [Project(name=str(i), provenance=imported()) for i in range(5)]
        )
        assert len(store.unconfirmed(limit=2)) == 2

    def test_confirming_moves_record_out_of_queue(self, store):
        p = store.put(Project(name="Haru", provenance=imported()))
        assert len(store.unconfirmed()) == 1

        store.put(p.model_copy(update={"provenance": p.provenance.confirm()}))
        assert store.unconfirmed() == []
        assert len(store.list(Project, confirmed_only=True)) == 1


class TestVersioning:
    """PRD §6.1 — facts are versioned and history is kept."""

    def test_update_bumps_version(self, store):
        p = store.put(Project(name="v1", provenance=imported()))
        assert p.version == 1
        p2 = store.put(p.model_copy(update={"name": "v2"}))
        assert p2.version == 2
        assert store.get(Project, p.id).name == "v2"

    def test_previous_payload_is_archived(self, store):
        p = store.put(Project(name="v1", provenance=imported()))
        store.put(p.model_copy(update={"name": "v2"}))
        store.put(store.get(Project, p.id).model_copy(update={"name": "v3"}))

        hist = store.history(p.id)
        assert [h["version"] for h in hist] == [1, 2]
        assert [h["payload"]["name"] for h in hist] == ["v1", "v2"]

    def test_update_does_not_duplicate_rows(self, store):
        p = store.put(Project(name="v1", provenance=imported()))
        store.put(p.model_copy(update={"name": "v2"}))
        assert len(store.list(Project)) == 1


class TestSingletons:
    def test_round_trip(self, store):
        store.put_singleton(
            Identity(legal_name=Attested.entered("Ada Lovelace"), city=Attested.entered("London"))
        )
        got = store.get_singleton(Identity)
        assert got.legal_name.value == "Ada Lovelace"
        assert got.legal_name.is_confirmed

    def test_missing_returns_none(self, store):
        assert store.get_singleton(Compensation) is None

    def test_overwrites_in_place(self, store):
        store.put_singleton(Preferences(tone=Tone.FORMAL))
        store.put_singleton(Preferences(tone=Tone.WARM))
        assert store.get_singleton(Preferences).tone is Tone.WARM

    def test_sensitive_defaults_persist(self, store):
        store.put_singleton(Compensation())
        assert store.get_singleton(Compensation).current_salary is None


class TestProfileScoping:
    def test_records_are_isolated_by_profile(self, store):
        store.put(Project(name="industry", provenance=imported(), profile_id="industry"))
        store.put(Project(name="academic", provenance=imported(), profile_id="academic"))

        assert [p.name for p in store.list(Project, profile_id="industry")] == ["industry"]
        assert [p.name for p in store.list(Project, profile_id="academic")] == ["academic"]

    def test_singletons_are_isolated_by_profile(self, store):
        store.put_singleton(Preferences(profile_id="a", tone=Tone.FORMAL))
        store.put_singleton(Preferences(profile_id="b", tone=Tone.WARM))
        assert store.get_singleton(Preferences, profile_id="a").tone is Tone.FORMAL
        assert store.get_singleton(Preferences, profile_id="b").tone is Tone.WARM

    def test_profiles_lists_distinct(self, store):
        store.put(Project(name="x", provenance=imported(), profile_id="a"))
        store.put(Project(name="y", provenance=imported(), profile_id="b"))
        assert list(store.profiles()) == ["a", "b"]

    def test_unconfirmed_is_profile_scoped(self, store):
        store.put(Project(name="x", provenance=imported(), profile_id="a"))
        store.put(Project(name="y", provenance=imported(), profile_id="b"))
        assert [r.name for r in store.unconfirmed(profile_id="a")] == ["x"]


class TestPersistenceAndSchema:
    def test_data_survives_reopen(self, tmp_path):
        path = tmp_path / "brain.sqlite"
        s1 = BrainStore(path)
        s1.put(Credential(name="AWS SA", provenance=confirmed(), document_ref="d1"))
        s1.close()

        s2 = BrainStore(path)
        creds = s2.list(Credential)
        assert len(creds) == 1
        assert creds[0].is_claimable
        s2.close()

    def test_init_is_idempotent(self, tmp_path):
        path = tmp_path / "brain.sqlite"
        BrainStore(path).close()
        s = BrainStore(path)
        assert s.list(Project) == []
        s.close()

    def test_counts(self, store):
        store.put(Project(name="p", provenance=imported()))
        store.put_many([Skill(name="a", provenance=imported()), Skill(name="b", provenance=imported())])
        assert store.counts() == {"project": 1, "skill": 2}

    def test_unregistered_model_is_rejected(self):
        class Rogue(Project):
            pass

        with pytest.raises(UnknownKindError):
            record_kind(Rogue)

    def test_kind_names_are_stable(self):
        # Renaming these strings silently orphans existing rows.
        assert record_kind(Project) == "project"
        assert record_kind(Credential) == "credential"
