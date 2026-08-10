"""Tests for the review queue (PRD §6.3)."""

import pytest

from haru.brain.fact_boundary import derive
from haru.brain.models import Credential, Experience, Project, Skill
from haru.brain.provenance import Provenance, Source
from haru.brain.review import ReviewQueue
from haru.brain.store import BrainStore


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "brain.sqlite")
    yield s
    s.close()


@pytest.fixture
def queue(store):
    return ReviewQueue(store)


def imported(confidence: float | None = None) -> Provenance:
    return Provenance.create(Source.CV_IMPORT, confidence=confidence)


class TestPending:
    def test_empty_brain(self, queue):
        assert queue.pending() == []
        assert queue.is_empty()

    def test_imports_appear(self, store, queue):
        store.put(Project(name="Haru", provenance=imported()))
        assert queue.count() == 1
        assert queue.pending()[0].record.name == "Haru"

    def test_confirmed_records_absent(self, store, queue):
        store.put(Project(name="Haru", provenance=Provenance.entered()))
        assert queue.is_empty()

    def test_flagged_items_sort_first(self, store, queue):
        store.put(Project(name="plain", provenance=imported()))
        store.put(Skill(name="no-evidence", provenance=imported()))

        first = queue.pending()[0]
        assert first.record.name == "no-evidence"
        assert first.reasons

    def test_more_flags_sort_earlier(self, store, queue):
        store.put(Project(name="plain", provenance=imported()))
        store.put(
            Credential(name="Lapsed", provenance=Provenance.create(Source.INFERRED))
        )
        names = [i.record.name for i in queue.pending()]
        assert names[0] == "Lapsed"

    def test_limit(self, store, queue):
        for i in range(5):
            store.put(Project(name=str(i), provenance=imported()))
        assert len(queue.pending(limit=2)) == 2

    def test_profile_scoped(self, store, queue):
        store.put(Project(name="a", provenance=imported(), profile_id="a"))
        store.put(Project(name="b", provenance=imported(), profile_id="b"))
        assert [i.record.name for i in queue.pending(profile_id="a")] == ["a"]


class TestReasons:
    def test_credential_without_document_is_flagged(self, store, queue):
        store.put(Credential(name="AWS SA", provenance=imported()))
        reasons = queue.pending()[0].reasons
        assert any("document" in r for r in reasons)

    def test_skill_without_evidence_is_flagged(self, store, queue):
        store.put(Skill(name="Rust", provenance=imported()))
        assert any("evidence" in r for r in queue.pending()[0].reasons)

    def test_skill_with_evidence_is_not_flagged(self, store, queue):
        store.put(Skill(name="Python", provenance=imported(), evidence_refs=["p1"]))
        assert queue.pending()[0].reasons == ()

    def test_low_confidence_is_flagged(self, store, queue):
        store.put(Project(name="Haru", provenance=imported(confidence=0.2)))
        assert any("confidence" in r for r in queue.pending()[0].reasons)

    def test_inferred_source_is_flagged(self, store, queue):
        store.put(Project(name="Haru", provenance=Provenance.create(Source.INFERRED)))
        assert any("inferred" in r for r in queue.pending()[0].reasons)

    def test_clean_import_has_no_reasons(self, store, queue):
        store.put(Project(name="Haru", provenance=imported()))
        assert queue.pending()[0].reasons == ()


class TestConfirm:
    def test_confirm_removes_from_queue(self, store, queue):
        store.put(Project(name="Haru", provenance=imported()))
        queue.confirm(queue.pending()[0].record)
        assert queue.is_empty()

    def test_confirm_widens_the_fact_boundary(self, store, queue):
        store.put(Project(name="Haru", provenance=imported()))
        assert not derive(store).allows_project("Haru")

        queue.confirm(queue.pending()[0].record)
        assert derive(store).allows_project("Haru")

    def test_confirm_is_idempotent(self, store, queue):
        p = store.put(Project(name="Haru", provenance=imported()))
        first = queue.confirm(p)
        again = queue.confirm(first)
        assert again.provenance.confirmed
        assert again.version == first.version, "no-op must not bump version"

    def test_confirm_preserves_original_source(self, store, queue):
        store.put(Project(name="Haru", provenance=imported()))
        confirmed = queue.confirm(queue.pending()[0].record)
        assert confirmed.provenance.source is Source.CV_IMPORT

    def test_confirm_many(self, store, queue):
        store.put(Project(name="a", provenance=imported()))
        store.put(Project(name="b", provenance=imported()))
        queue.confirm_many([i.record for i in queue.pending()])
        assert queue.is_empty()


class TestEdit:
    def test_edit_changes_the_value(self, store, queue):
        p = store.put(Project(name="Hairu", provenance=imported()))
        edited = queue.edit(p, name="Haru")
        assert edited.name == "Haru"
        assert store.get(Project, p.id).name == "Haru"

    def test_edit_confirms(self, store, queue):
        p = store.put(Project(name="Hairu", provenance=imported()))
        edited = queue.edit(p, name="Haru")
        assert edited.provenance.confirmed
        assert queue.is_empty()

    def test_edit_takes_ownership_of_provenance(self, store, queue):
        p = store.put(Project(name="Hairu", provenance=imported()))
        edited = queue.edit(p, name="Haru")
        assert edited.provenance.source is Source.USER_ENTERED
        assert "cv_import" in edited.provenance.detail

    def test_edit_archives_the_import(self, store, queue):
        p = store.put(Project(name="Hairu", provenance=imported()))
        queue.edit(p, name="Haru")
        history = store.history(p.id)
        assert history[0]["payload"]["name"] == "Hairu"

    def test_edit_without_changes_just_confirms(self, store, queue):
        p = store.put(Project(name="Haru", provenance=imported()))
        edited = queue.edit(p)
        assert edited.provenance.confirmed
        assert edited.provenance.source is Source.CV_IMPORT

    def test_edit_multiple_fields(self, store, queue):
        e = store.put(Experience(org="Acme", title="dev", provenance=imported()))
        edited = queue.edit(e, org="Acme Corp", title="Senior Engineer")
        assert edited.org == "Acme Corp"
        assert edited.title == "Senior Engineer"


class TestReject:
    def test_reject_deletes(self, store, queue):
        p = store.put(Project(name="Haru", provenance=imported()))
        assert queue.reject(p)
        assert store.get(Project, p.id) is None
        assert queue.is_empty()

    def test_reject_missing_returns_false(self, store, queue):
        p = Project(name="ghost", provenance=imported())
        assert not queue.reject(p)

    def test_rejected_fact_never_reaches_the_boundary(self, store, queue):
        p = store.put(Project(name="Haru", provenance=imported()))
        queue.reject(p)
        assert not derive(store).allows_project("Haru")

    def test_reject_many(self, store, queue):
        store.put(Project(name="a", provenance=imported()))
        store.put(Project(name="b", provenance=imported()))
        assert queue.reject_many([i.record for i in queue.pending()]) == 2


class TestConfirmClean:
    """PRD §14.4 — bulk-accept the routine tail only."""

    def test_confirms_unflagged_records(self, store, queue):
        store.put(Project(name="clean", provenance=imported()))
        confirmed = queue.confirm_clean()
        assert [c.name for c in confirmed] == ["clean"]

    def test_leaves_flagged_records_pending(self, store, queue):
        store.put(Project(name="clean", provenance=imported()))
        store.put(Credential(name="AWS SA", provenance=imported()))

        queue.confirm_clean()
        remaining = [i.record.name for i in queue.pending()]
        assert remaining == ["AWS SA"], "flagged items must be reviewed individually"

    def test_flagged_credential_stays_unclaimable(self, store, queue):
        store.put(Credential(name="AWS SA", provenance=imported()))
        queue.confirm_clean()
        assert not derive(store).allows_credential("AWS SA")

    def test_empty_queue(self, store, queue):
        assert list(queue.confirm_clean()) == []
