"""Tests for the local control panel (PRD §14.2, §16.1).

The one that matters most is :class:`TestApprovalGate` — the UI must not be a
way around the safety rules. A page that lets you click Approve on a plan with
blockers would undo every interlock underneath it.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from haru.adapters.fields import FieldMapper
from haru.adapters.job import extract_ask, score_fit
from haru.adapters.plan import build_plan
from haru.api.app import create_app
from haru.api.registry import (
    ApprovalExpired,
    ApprovalRegistry,
    Decision,
    NotSubmittable,
)
from haru.brain.fact_boundary import derive
from haru.brain.models import (
    Experience,
    Identity,
    Project,
    Skill,
    StandardAnswers,
    WorkAuthorization,
)
from haru.brain.provenance import Attested, Provenance, Source
from haru.brain.store import BrainStore
from haru.execution.page import Element, ElementRole, PageSnapshot
from haru.validation.seam import reset_validator, set_validator
from haru.validation.validator import FactBoundaryValidator

POSTING = """Role: Backend Engineer
Company: Northwind Systems
Looking for Python and PostgreSQL. Docker required."""


@pytest.fixture(autouse=True)
def _real_validator():
    set_validator(FactBoundaryValidator())
    yield
    reset_validator()


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "brain.sqlite")
    ok = Provenance.entered
    s.put_singleton(
        Identity(
            legal_name=Attested.entered("Ada Lovelace"),
            emails=[Attested.entered("ada@example.com")],
            phones=[Attested.entered("+44 20 7946 0000")],
        )
    )
    s.put_singleton(WorkAuthorization(legally_authorized_in=["GB"], requires_sponsorship=False))
    s.put_singleton(StandardAnswers(age_18_or_over=True))
    s.put(
        Experience(
            org="Northwind Systems", title="Backend Engineer", provenance=ok(),
            technologies=["Python", "PostgreSQL", "Docker"],
        )
    )
    for name in ("Python", "PostgreSQL", "Docker"):
        s.put(Skill(name=name, provenance=ok(), evidence_refs=["e1"]))
    yield s
    s.close()


def snapshot(*extra: Element) -> PageSnapshot:
    base = [
        Element(index=0, role=ElementRole.TEXTBOX, label="Full name", selector="#n", tag="input", required=True),
        Element(index=1, role=ElementRole.TEXTBOX, label="Email", selector="#e", tag="input", required=True),
        Element(index=2, role=ElementRole.BUTTON, label="Submit", selector="#s", tag="button"),
    ]
    return PageSnapshot(
        url="https://boards.greenhouse.io/northwind/jobs/1",
        title="Backend Engineer at Northwind Systems",
        elements=tuple(base + list(extra)),
        text=POSTING,
    )


def make_plan(store, page=None, generated=None):
    page = page or snapshot()
    ask = extract_ask(POSTING, url=page.url, title=page.title)
    boundary = derive(store)
    return build_plan(
        page, FieldMapper.from_store(store), ask, score_fit(ask, boundary),
        boundary, generated=generated,
    )


@pytest.fixture
def registry():
    return ApprovalRegistry()


@pytest.fixture
def client(store, registry):
    return TestClient(create_app(store=store, registry=registry))


class TestQueuePage:
    def test_empty_queue(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Nothing waiting" in response.text

    def test_lists_pending(self, client, store, registry):
        registry.submit(make_plan(store))
        body = client.get("/").text
        assert "Backend Engineer" in body
        assert "Northwind Systems" in body

    def test_shows_ready_state(self, client, store, registry):
        registry.submit(make_plan(store))
        assert "ready" in client.get("/").text

    def test_shows_blocking_count(self, client, store, registry):
        page = snapshot(
            Element(index=3, role=ElementRole.TEXTBOX, label="Favourite colour",
                    selector="#c", tag="input", required=True)
        )
        registry.submit(make_plan(store, page))
        assert "blocking" in client.get("/").text

    def test_most_demanding_first(self, registry, store):
        easy = registry.submit(make_plan(store))
        hard = registry.submit(
            make_plan(store, snapshot(
                Element(index=3, role=ElementRole.SELECT, label="Gender",
                        selector="#g", tag="select")))
        )
        assert [i.id for i in registry.pending()][0] == hard.id
        assert easy.id in [i.id for i in registry.pending()]


class TestApprovalPage:
    def test_shows_every_value_that_will_be_entered(self, client, store, registry):
        item = registry.submit(make_plan(store))
        body = client.get(f"/approve/{item.id}").text
        assert "Ada Lovelace" in body
        assert "ada@example.com" in body

    def test_shows_fit_reasoning(self, client, store, registry):
        item = registry.submit(make_plan(store))
        assert "match" in client.get(f"/approve/{item.id}").text

    def test_shows_generated_text_verbatim(self, client, store, registry):
        item = registry.submit(
            make_plan(store, generated={"Why us?": "I used Python at Northwind Systems."})
        )
        body = client.get(f"/approve/{item.id}").text
        assert "Why us?" in body
        assert "I used Python at Northwind Systems." in body

    def test_lists_fields_needing_the_user(self, client, store, registry):
        page = snapshot(
            Element(index=3, role=ElementRole.SELECT, label="Gender", selector="#g", tag="select")
        )
        item = registry.submit(make_plan(store, page))
        body = client.get(f"/approve/{item.id}").text
        assert "Needs you" in body
        assert "Gender" in body
        assert "sensitive" in body

    def test_names_requirements_not_on_file(self, client, store, registry):
        page = snapshot()
        ask = extract_ask("Python required. Kubernetes a plus.", url=page.url)
        boundary = derive(store)
        plan = build_plan(page, FieldMapper.from_store(store), ask, score_fit(ask, boundary), boundary)
        item = registry.submit(plan)
        body = client.get(f"/approve/{item.id}").text
        assert "Not on file" in body
        assert "Kubernetes" in body

    def test_missing_approval_is_handled(self, client):
        assert "No approval here" in client.get("/approve/nope").text


class TestApprovalGate:
    """The UI must not be a way around the safety rules."""

    def test_approve_button_disabled_when_blocked(self, client, store, registry):
        page = snapshot(
            Element(index=3, role=ElementRole.TEXTBOX, label="Favourite colour",
                    selector="#c", tag="input", required=True)
        )
        item = registry.submit(make_plan(store, page))
        body = client.get(f"/approve/{item.id}").text
        assert "Not ready to submit" in body
        assert "disabled" in body

    def test_posting_approve_on_a_blocked_plan_is_refused(self, client, store, registry):
        """Disabling the button is cosmetic; the server must refuse too."""
        page = snapshot(
            Element(index=3, role=ElementRole.TEXTBOX, label="Favourite colour",
                    selector="#c", tag="input", required=True)
        )
        item = registry.submit(make_plan(store, page))

        response = client.post(f"/approve/{item.id}", data={"action": "approve"})
        assert response.status_code == 200
        assert "Cannot approve yet" in response.text
        assert item.status is Decision.PENDING

    def test_fabricated_text_blocks_approval(self, client, store, registry):
        item = registry.submit(
            make_plan(store, generated={"Why?": "I am an AWS Certified Solutions Architect."})
        )
        response = client.post(f"/approve/{item.id}", data={"action": "approve"})
        assert "Cannot approve yet" in response.text
        assert item.status is Decision.PENDING

    def test_clean_plan_can_be_approved(self, client, store, registry):
        item = registry.submit(make_plan(store))
        response = client.post(
            f"/approve/{item.id}", data={"action": "approve", "note": "looks right"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert item.status is Decision.APPROVED
        assert item.note == "looks right"

    def test_reject_always_allowed(self, client, store, registry):
        page = snapshot(
            Element(index=3, role=ElementRole.TEXTBOX, label="Favourite colour",
                    selector="#c", tag="input", required=True)
        )
        item = registry.submit(make_plan(store, page))
        client.post(f"/approve/{item.id}", data={"action": "reject"}, follow_redirects=False)
        assert item.status is Decision.REJECTED

    def test_stubbed_validation_blocks_and_warns(self, store, registry):
        reset_validator()
        client = TestClient(create_app(store=store, registry=registry))
        item = registry.submit(make_plan(store))

        assert "Validation is stubbed" in client.get("/").text
        response = client.post(f"/approve/{item.id}", data={"action": "approve"})
        assert "Cannot approve yet" in response.text
        assert item.status is Decision.PENDING


class TestRegistry:
    def test_approve_refuses_blocked_plan(self, store, registry):
        page = snapshot(
            Element(index=3, role=ElementRole.TEXTBOX, label="Colour", selector="#c",
                    tag="input", required=True)
        )
        item = registry.submit(make_plan(store, page))
        with pytest.raises(NotSubmittable):
            registry.approve(item.id)

    def test_expired_approval_cannot_be_approved(self, store, registry):
        item = registry.submit(make_plan(store), ttl=timedelta(seconds=-1))
        assert item.status is Decision.EXPIRED
        with pytest.raises(ApprovalExpired):
            registry.approve(item.id)

    def test_expired_drops_out_of_pending(self, store, registry):
        registry.submit(make_plan(store), ttl=timedelta(seconds=-1))
        assert registry.pending() == []

    def test_decided_history(self, store, registry):
        item = registry.submit(make_plan(store))
        registry.approve(item.id)
        assert [i.id for i in registry.decided()] == [item.id]

    def test_unknown_id(self, registry):
        with pytest.raises(KeyError):
            registry.approve("nope")

    def test_empty_registry_is_falsy(self, registry):
        """Guards the injection bug below: __len__ makes an empty one falsy."""
        assert not registry
        assert len(registry) == 0

    def test_injected_empty_registry_is_actually_used(self, store):
        """Regression: `registry or ApprovalRegistry()` discarded the caller's.

        The symptom was approvals vanishing — submitted into one object while
        the pages read another.
        """
        injected = ApprovalRegistry()
        app = create_app(store=store, registry=injected)
        assert app.state.registry is injected

        item = injected.submit(make_plan(store))
        assert item.title in TestClient(app).get("/").text


class TestBrainPage:
    def test_lists_unconfirmed_records(self, client, store):
        store.put(Project(name="Pending Project", provenance=Provenance.create(Source.CV_IMPORT)))
        body = client.get("/brain").text
        assert "Pending Project" in body

    def test_shows_why_a_record_needs_attention(self, client, store):
        store.put(Skill(name="Rust", provenance=Provenance.create(Source.CV_IMPORT)))
        assert "evidence" in client.get("/brain").text

    def test_confirming_removes_it_from_the_queue(self, client, store):
        record = store.put(Project(name="Pending", provenance=Provenance.create(Source.CV_IMPORT)))
        client.post(f"/brain/{record.id}", data={"action": "confirm"}, follow_redirects=False)
        assert "Pending" not in client.get("/brain").text
        assert derive(store).allows_project("Pending")

    def test_discarding_deletes_it(self, client, store):
        record = store.put(Project(name="Junk", provenance=Provenance.create(Source.CV_IMPORT)))
        client.post(f"/brain/{record.id}", data={"action": "reject"}, follow_redirects=False)
        assert store.get(Project, record.id) is None

    def test_empty_queue_message(self, client):
        assert "Nothing to review" in client.get("/brain").text


class TestJson:
    def test_health(self, client):
        payload = client.get("/api/health").json()
        assert payload["ok"] is True
        assert payload["validation_stubbed"] is False

    def test_approval_payload(self, client, store, registry):
        item = registry.submit(make_plan(store))
        payload = client.get(f"/api/approvals/{item.id}").json()
        assert payload["submittable"] is True
        assert payload["blockers"] == []
        assert any(f["value"] == "Ada Lovelace" for f in payload["fill"])

    def test_unknown_approval(self, client):
        assert "error" in client.get("/api/approvals/nope").json()


class TestWebviewSafety:
    """Nothing may depend on a URL bar, extensions, or network access."""

    def test_stylesheet_is_local(self, client):
        assert client.get("/static/app.css").status_code == 200

    def test_no_external_resources(self, client, store, registry):
        item = registry.submit(make_plan(store))
        for path in ["/", f"/approve/{item.id}", "/brain"]:
            body = client.get(path).text
            assert "http://" not in body.replace("https://boards.greenhouse.io", "")
            assert "cdn." not in body
            assert "<script" not in body, "no JS needed yet; keep it that way"
