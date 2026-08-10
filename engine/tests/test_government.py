"""Tests for high-stakes forms and the evidence record (PRD §8.3, §14.3)."""

from datetime import date

import pytest

from haru.adapters.fields import FieldMapper
from haru.adapters.government import (
    DISCLAIMER,
    HighStakesReview,
    build_government_plan,
    is_critical,
    looks_official,
)
from haru.adapters.plan import Disposition
from haru.brain.fact_boundary import derive
from haru.brain.models import Identity, Skill, WorkAuthorization
from haru.brain.provenance import Attested, Provenance
from haru.brain.store import BrainStore
from haru.evidence import DocumentEntry, EvidenceRecord, build_record, sha256
from haru.execution.page import Element, ElementRole, PageSnapshot
from haru.models.providers import EchoProvider, ScriptedCloudProvider
from haru.models.router import ModelRouter
from haru.models.types import CloudDisabled, TaskKind, Tier
from haru.validation.seam import reset_validator, set_validator
from haru.validation.validator import FactBoundaryValidator


@pytest.fixture(autouse=True)
def _real_validator():
    set_validator(FactBoundaryValidator())
    yield
    reset_validator()


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "brain.sqlite")
    s.put_singleton(
        Identity(
            legal_name=Attested.entered("Ada Lovelace"),
            emails=[Attested.entered("ada@example.com")],
            city=Attested.entered("London"),
            date_of_birth=Attested.entered(date(1990, 12, 10)),
            national_ids=[Attested.entered("123-45-6789")],
        )
    )
    s.put_singleton(WorkAuthorization(legally_authorized_in=["GB"], citizenships=["GB"]))
    s.put(Skill(name="Python", provenance=Provenance.entered(), evidence_refs=["e1"]))
    yield s
    s.close()


def form() -> PageSnapshot:
    return PageSnapshot(
        url="https://www.gov.uk/apply/visa",
        title="Visa application",
        text="Official use only. Complete all sections.",
        elements=(
            Element(index=0, role=ElementRole.TEXTBOX, label="Full name", selector="#n", tag="input", required=True),
            Element(index=1, role=ElementRole.TEXTBOX, label="Email", selector="#e", tag="input"),
            Element(index=2, role=ElementRole.TEXTBOX, label="Passport number", selector="#p", tag="input", required=True),
            Element(index=3, role=ElementRole.TEXTBOX, label="Date of birth", selector="#d", tag="input", required=True),
            Element(index=4, role=ElementRole.TEXTBOX, label="City", selector="#c", tag="input"),
            Element(index=5, role=ElementRole.BUTTON, label="Submit", selector="#s", tag="button"),
        ),
    )


@pytest.fixture
def review(store):
    return build_government_plan(form(), FieldMapper.from_store(store), derive(store))


class TestRecognition:
    @pytest.mark.parametrize(
        "url",
        ["https://www.gov.uk/apply", "https://travel.state.gov/x", "https://ircc.canada.ca/f"],
    )
    def test_official_hosts(self, url):
        assert looks_official(url)

    def test_ordinary_site_is_not_official(self):
        assert not looks_official("https://boards.greenhouse.io/x/jobs/1")

    def test_detected_from_page_text(self):
        assert looks_official("https://example.com/f", "For official use only. USCIS form.")

    @pytest.mark.parametrize(
        "label",
        ["Passport number", "Date of birth", "National Insurance number",
         "Any criminal convictions?", "Nationality", "Previous names"],
    )
    def test_critical_fields(self, label):
        assert is_critical(label)

    @pytest.mark.parametrize("label", ["Email", "City", "How did you hear about us?"])
    def test_ordinary_fields(self, label):
        assert not is_critical(label)


class TestThresholds:
    """PRD §8.3 — 0.95 rather than 0.80."""

    def test_moderate_confidence_is_not_auto_filled(self, store):
        snapshot = PageSnapshot(
            url="https://www.gov.uk/f",
            elements=(
                Element(index=0, role=ElementRole.TEXTBOX,
                        label="Please give your email so we can reply",
                        selector="#e", tag="input"),
            ),
        )
        review = build_government_plan(snapshot, FieldMapper.from_store(store), derive(store))
        assert review.plan.to_fill == [], "0.855 confidence is not enough here"

    def test_exact_match_still_fills(self, review):
        assert any(f.match.canonical == "email" for f in review.plan.to_fill)

    def test_critical_field_is_never_auto_filled(self, review):
        """Even a confident guess at a passport number must be confirmed."""
        labels = {f.label for f in review.plan.to_fill}
        assert "Passport number" not in labels
        asked = {f.label for f in review.plan.to_ask}
        assert "Passport number" in asked

    def test_critical_field_says_why(self, review):
        entry = next(f for f in review.plan.to_ask if f.label == "Passport number")
        assert "identity-critical" in entry.reason
        assert entry.disposition is Disposition.ASK


class TestFieldByFieldAcknowledgement:
    def test_unconfirmed_fields_block_submission(self, review):
        assert not review.is_submittable
        assert any("not yet confirmed" in b for b in review.blockers())

    def test_confirming_one_does_not_confirm_the_rest(self, review):
        first = review.plan.to_fill[0].label
        review.acknowledge(first)
        assert first not in {f.label for f in review.pending}
        assert review.pending, "the others still need confirming"

    def test_all_confirmed_makes_it_submittable(self, review):
        for entry in list(review.plan.to_fill):
            review.acknowledge(entry.label)
        # The remaining blockers are unanswered required fields, not acknowledgement.
        assert not any("not yet confirmed" in b for b in review.blockers())

    def test_acknowledging_an_unknown_field_fails(self, review):
        assert not review.acknowledge("Nonexistent field")

    def test_progress_is_reported(self, review):
        assert review.progress.startswith("0/")
        review.acknowledge(review.plan.to_fill[0].label)
        assert review.progress.startswith("1/")

    def test_critical_pending_fields_are_marked(self, store):
        snapshot = PageSnapshot(
            url="https://www.gov.uk/f",
            elements=(
                Element(index=0, role=ElementRole.TEXTBOX, label="Full name",
                        selector="#n", tag="input"),
            ),
        )
        review = build_government_plan(snapshot, FieldMapper.from_store(store), derive(store))
        review.plan.to_fill and review.blockers()
        assert "Full name" in review.preview()


class TestCloudIsBlocked:
    """PRD §13.2 rule 3 — nothing on an official form reaches a third party."""

    def test_router_is_switched_into_high_stakes(self, store):
        router = ModelRouter(
            {Tier.CLOUD: ScriptedCloudProvider(), Tier.LOCAL_SMALL: EchoProvider()},
            store=store,
            allow_cloud=True,
        )
        assert router.cloud_permitted()

        build_government_plan(form(), FieldMapper.from_store(store), derive(store), router=router)
        assert not router.cloud_permitted(), "the adapter must enforce this itself"

    def test_cloud_call_raises_afterwards(self, store):
        router = ModelRouter({Tier.CLOUD: ScriptedCloudProvider()}, store=store, allow_cloud=True)
        build_government_plan(form(), FieldMapper.from_store(store), derive(store), router=router)
        with pytest.raises(CloudDisabled):
            router.run(TaskKind.POLISH_PROSE, "anything")


class TestDisclaimer:
    def test_states_what_haru_is_not(self):
        assert "not a lawyer" in DISCLAIMER
        assert "eligible" in DISCLAIMER

    def test_appears_in_the_preview(self, review):
        assert DISCLAIMER in review.preview()


class TestPreview:
    def test_does_not_show_a_job_fit_score(self, review):
        """'0/10 — no overlap' is meaningless on a visa form."""
        preview = review.preview()
        assert "Fit:" not in preview
        assert "no overlap" not in preview

    def test_shows_the_value_on_file_for_fields_it_asks_about(self, review):
        """Confirming a known value beats retyping a passport number."""
        preview = review.preview()
        assert "Date of birth" in preview
        assert "on file:" in preview
        assert "1990-12-10" in preview

    def test_names_the_form(self, review):
        assert "gov.uk" in review.preview()


class TestDateOfBirth:
    def test_is_never_auto_filled(self, store):
        from haru.adapters.fields import FieldMapper as Mapper

        match = Mapper.from_store(store).match("Date of birth")
        assert match.always_ask
        assert match.sensitive
        assert not match.is_auto_fillable()

    def test_surfaces_the_stored_value(self, store):
        from haru.adapters.fields import FieldMapper as Mapper

        assert Mapper.from_store(store).match("Date of birth").value == "1990-12-10"

    @pytest.mark.parametrize("label", ["Date of Birth", "DOB", "Birth date"])
    def test_label_variants(self, store, label):
        from haru.adapters.fields import FieldMapper as Mapper

        assert Mapper.from_store(store).match(label).canonical == "date_of_birth"


class TestEvidenceRecord:
    def test_captures_fields_and_sources(self, review):
        record = build_record(review.plan, high_stakes=True)
        assert record.high_stakes
        assert any(f.label == "Email" for f in record.fields)
        assert all(f.source for f in record.fields)

    def test_records_acknowledgement(self, review):
        label = review.plan.to_fill[0].label
        review.acknowledge(label)
        record = build_record(review.plan, high_stakes=True, acknowledged=review.acknowledged)
        assert next(f for f in record.fields if f.label == label).acknowledged

    def test_documents_are_identified_by_hash(self):
        content = b"%PDF-1.4 passport scan"
        record = EvidenceRecord(
            documents=(
                DocumentEntry(filename="passport.pdf", digest=sha256(content),
                              size_bytes=len(content), consented=True),
            )
        )
        assert record.documents[0].digest == sha256(content)
        assert record.documents[0].consented

    def test_digest_is_stable(self, review):
        record = build_record(review.plan)
        assert record.digest() == record.digest()
        assert record.verify(record.digest())

    def test_altering_the_record_changes_the_digest(self, review):
        record = build_record(review.plan)
        original = record.digest()
        tampered = record.model_copy(update={"org": "Someone Else"})
        assert tampered.digest() != original
        assert not tampered.verify(original)

    def test_records_unverified_actions(self, review):
        from haru.execution.actions import Action, ActionType
        from haru.execution.loop import Step

        steps = [
            Step(action=Action(action_type=ActionType.FILL, target=0, value="x"),
                 performed=True, verified=False, note="did not stick"),
        ]
        record = build_record(review.plan, steps=steps)
        assert len(record.unverified_actions) == 1

    def test_json_export_includes_the_digest(self, review, tmp_path):
        record = build_record(review.plan, high_stakes=True)
        path = record.write(tmp_path / "evidence" / "record.json")
        assert path.exists()

        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["digest"] == record.digest()
        assert payload["high_stakes"] is True

    def test_summary_is_readable(self, review):
        record = build_record(review.plan, high_stakes=True)
        summary = record.summary()
        assert "high-stakes" in summary
        assert "digest" in summary

    def test_records_models_used(self, review):
        record = build_record(review.plan, models_used=("ollama:gemma3:4b",))
        assert "ollama:gemma3:4b" in record.models_used

    def test_approval_is_recorded(self, review):
        assert not build_record(review.plan).approved_by_user
        assert build_record(review.plan, approved_by_user=True).approved_by_user
