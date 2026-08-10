"""Tests for the job adapter: extraction, fit, and the approval plan (PRD §8.1, §14.2)."""

from datetime import date

import pytest

from haru.adapters.fields import FieldMapper
from haru.adapters.job import Fit, detect_ats, extract_ask, extract_requirements, score_fit
from haru.adapters.plan import Disposition, build_plan
from haru.brain.fact_boundary import derive
from haru.brain.models import (
    Availability,
    Compensation,
    Experience,
    Identity,
    Project,
    Skill,
    StandardAnswers,
    WorkAuthorization,
)
from haru.brain.provenance import Attested, Provenance
from haru.brain.store import BrainStore
from haru.execution.page import Element, ElementRole, PageSnapshot
from haru.validation.seam import reset_validator, set_validator
from haru.validation.validator import FactBoundaryValidator

POSTING = """
Role: Backend Engineer
Company: Northwind Systems

We are looking for someone comfortable with Python and PostgreSQL.
Experience with Docker is required. Familiarity with Kubernetes and
Terraform is a plus. You will build REST APIs and own services end to end.
"""


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
            city=Attested.entered("London"),
        )
    )
    s.put_singleton(WorkAuthorization(legally_authorized_in=["GB"], requires_sponsorship=False))
    s.put_singleton(Availability(earliest_start_date=date(2026, 9, 1)))
    s.put_singleton(Compensation(expectation=90000))
    s.put_singleton(StandardAnswers(age_18_or_over=True))
    s.put(
        Experience(
            org="Northwind Systems",
            title="Backend Engineer",
            provenance=ok(),
            technologies=["Python", "PostgreSQL", "Docker"],
        )
    )
    s.put(Project(name="Haru", provenance=ok(), technologies=["Python", "SQLite"]))
    for name in ("Python", "PostgreSQL", "Docker"):
        s.put(Skill(name=name, provenance=ok(), evidence_refs=["e1"]))
    yield s
    s.close()


def form(*extra: Element) -> PageSnapshot:
    base = [
        Element(index=0, role=ElementRole.TEXTBOX, label="Full name", selector="#n", tag="input", required=True),
        Element(index=1, role=ElementRole.TEXTBOX, label="Email", selector="#e", tag="input", required=True),
        Element(index=2, role=ElementRole.TEXTBOX, label="Phone", selector="#p", tag="input"),
        Element(index=3, role=ElementRole.BUTTON, label="Submit", selector="#s", tag="button"),
    ]
    return PageSnapshot(
        url="https://boards.greenhouse.io/northwind/jobs/1",
        title="Backend Engineer at Northwind Systems",
        elements=tuple(base + list(extra)),
        text=POSTING,
    )


class TestExtraction:
    def test_finds_requirements(self):
        reqs = {r.lower() for r in extract_requirements(POSTING)}
        assert "python" in reqs
        assert "postgresql" in reqs
        assert "docker" in reqs

    def test_ignores_generic_vocabulary(self):
        reqs = {r.lower() for r in extract_requirements(POSTING)}
        assert "rest" not in reqs
        assert "apis" not in reqs

    def test_finds_technology_at_sentence_start(self):
        """Regression: a missed requirement silently inflates the fit score."""
        reqs = {r.lower() for r in extract_requirements("Kubernetes a plus. Docker required.")}
        assert "kubernetes" in reqs
        assert "docker" in reqs

    def test_missed_requirement_does_not_inflate_fit(self, store):
        ask = extract_ask("Python required. Kubernetes a plus.")
        fit = score_fit(ask, derive(store))
        assert fit.score < 1.0, "Kubernetes is not on file — fit must reflect that"
        assert any(m.lower() == "kubernetes" for m in fit.missing)

    def test_reads_role_and_company(self):
        ask = extract_ask(POSTING)
        assert ask.role == "Backend Engineer"
        assert ask.org == "Northwind Systems"

    def test_falls_back_to_page_title(self):
        ask = extract_ask("Some prose.", title="Data Engineer at Cedar Analytics")
        assert ask.role == "Data Engineer"
        assert ask.org == "Cedar Analytics"

    def test_empty_posting(self):
        assert extract_ask("").is_empty

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://boards.greenhouse.io/x/jobs/1", "Greenhouse"),
            ("https://jobs.lever.co/x/abc", "Lever"),
            ("https://x.myworkdayjobs.com/en-US/careers", "Workday"),
            ("https://jobs.ashbyhq.com/x", "Ashby"),
            ("https://example.com/careers", None),
        ],
    )
    def test_detects_ats(self, url, expected):
        assert detect_ats(url) == expected


class TestFit:
    def test_scores_coverage(self, store):
        fit = score_fit(extract_ask(POSTING), derive(store))
        assert 0 < fit.score < 1
        assert "Python" in fit.matched
        assert any(m.lower() == "kubernetes" for m in fit.missing)

    def test_full_coverage(self, store):
        from haru.cv.models import Ask

        fit = score_fit(Ask(requirements=("Python", "Docker")), derive(store))
        assert fit.score == 1.0
        assert fit.verdict == "strong match"
        assert fit.out_of_ten == 10

    def test_no_overlap_is_reported_honestly(self, store):
        from haru.cv.models import Ask

        fit = score_fit(Ask(requirements=("COBOL", "Fortran")), derive(store))
        assert fit.score == 0.0
        assert fit.verdict == "no overlap"
        assert "COBOL" in fit.summary()

    def test_empty_ask(self, store):
        from haru.cv.models import Ask

        assert score_fit(Ask(), derive(store)).score == 0.0

    def test_summary_names_the_gaps(self, store):
        fit = score_fit(extract_ask(POSTING), derive(store))
        assert "Not on file" in fit.summary()


class TestPlanFieldDecisions:
    def _plan(self, store, snapshot, **kwargs):
        ask = extract_ask(POSTING, url=snapshot.url, title=snapshot.title)
        boundary = derive(store)
        return build_plan(
            snapshot,
            FieldMapper.from_store(store),
            ask,
            score_fit(ask, boundary),
            boundary,
            **kwargs,
        )

    def test_known_fields_are_filled(self, store):
        plan = self._plan(store, form())
        filled = {p.match.canonical: p.match.value for p in plan.to_fill}
        assert filled["full_name"] == "Ada Lovelace"
        assert filled["email"] == "ada@example.com"

    def test_buttons_are_not_fields(self, store):
        plan = self._plan(store, form())
        assert all(p.element.label != "Submit" for p in plan.fields)

    def test_disabled_fields_are_ignored(self, store):
        snapshot = form(
            Element(index=4, role=ElementRole.TEXTBOX, label="Full name",
                    selector="#dup", tag="input", disabled=True)
        )
        plan = self._plan(store, snapshot)
        assert all(not p.element.disabled for p in plan.fields)

    def test_unknown_required_field_is_asked(self, store):
        snapshot = form(
            Element(index=4, role=ElementRole.TEXTBOX, label="Favourite colour",
                    selector="#c", tag="input", required=True)
        )
        plan = self._plan(store, snapshot)
        asked = {p.label for p in plan.to_ask}
        assert "Favourite colour" in asked

    def test_unknown_optional_field_is_skipped(self, store):
        snapshot = form(
            Element(index=4, role=ElementRole.TEXTBOX, label="Favourite colour",
                    selector="#c", tag="input")
        )
        plan = self._plan(store, snapshot)
        skipped = [p for p in plan.fields if p.disposition is Disposition.SKIP]
        assert any(p.label == "Favourite colour" for p in skipped)

    def test_sensitive_field_is_always_asked(self, store):
        snapshot = form(
            Element(index=4, role=ElementRole.SELECT, label="Gender",
                    selector="#g", tag="select", options=("", "Woman", "Man"))
        )
        plan = self._plan(store, snapshot)
        assert any(p.label == "Gender" for p in plan.sensitive_pending)
        assert all(p.match.canonical != "gender" for p in plan.to_fill)

    def test_high_threshold_shifts_fills_to_asks(self, store):
        relaxed = self._plan(store, form())
        strict = self._plan(store, form(), threshold=0.99)
        assert len(strict.to_fill) < len(relaxed.to_fill)


class TestPlanReadiness:
    def _plan(self, store, snapshot, generated=None):
        ask = extract_ask(POSTING, url=snapshot.url, title=snapshot.title)
        boundary = derive(store)
        return build_plan(
            snapshot,
            FieldMapper.from_store(store),
            ask,
            score_fit(ask, boundary),
            boundary,
            generated=generated,
        )

    def test_complete_plan_is_submittable(self, store):
        plan = self._plan(store, form())
        assert plan.is_submittable, plan.blockers()

    def test_unanswered_required_field_blocks(self, store):
        snapshot = form(
            Element(index=4, role=ElementRole.TEXTBOX, label="Favourite colour",
                    selector="#c", tag="input", required=True)
        )
        plan = self._plan(store, snapshot)
        assert not plan.is_submittable
        assert any("Favourite colour" in b for b in plan.blockers())

    def test_pending_sensitive_field_blocks(self, store):
        snapshot = form(
            Element(index=4, role=ElementRole.SELECT, label="Gender",
                    selector="#g", tag="select")
        )
        plan = self._plan(store, snapshot)
        assert not plan.is_submittable
        assert any("Gender" in b for b in plan.blockers())

    def test_fabricated_answer_blocks_submission(self, store):
        plan = self._plan(
            store,
            form(),
            generated={"Why us?": "I am an AWS Certified Solutions Architect."},
        )
        assert not plan.is_submittable
        assert any("blocked" in b for b in plan.blockers())

    def test_honest_answer_does_not_block(self, store):
        plan = self._plan(
            store,
            form(),
            generated={"Why us?": "I worked with Python and Docker at Northwind Systems."},
        )
        assert plan.is_submittable, plan.blockers()

    def test_stubbed_validation_blocks_everything(self, store):
        reset_validator()
        plan = self._plan(store, form())
        assert not plan.is_submittable
        assert any("stubbed" in b for b in plan.blockers())


class TestPlanOutput:
    def _plan(self, store, generated=None):
        snapshot = form()
        ask = extract_ask(POSTING, url=snapshot.url, title=snapshot.title)
        boundary = derive(store)
        return build_plan(
            snapshot,
            FieldMapper.from_store(store),
            ask,
            score_fit(ask, boundary),
            boundary,
            generated=generated,
        )

    def test_actions_cover_the_fills(self, store):
        plan = self._plan(store)
        actions = plan.actions()
        assert len(actions) == len(plan.to_fill)
        assert {a.value for a in actions} == {p.match.value for p in plan.to_fill}

    def test_actions_never_include_submit(self, store):
        from haru.execution.actions import ActionType

        assert all(a.action_type is ActionType.FILL for a in self._plan(store).actions())

    def test_actions_carry_their_reason(self, store):
        assert all(a.reason for a in self._plan(store).actions())

    def test_preview_shows_values_not_just_counts(self, store):
        preview = self._plan(store).preview()
        assert "Ada Lovelace" in preview
        assert "ada@example.com" in preview

    def test_preview_shows_fit(self, store):
        assert "Fit:" in self._plan(store).preview()

    def test_preview_states_readiness(self, store):
        assert "Ready to submit" in self._plan(store).preview()

    def test_preview_lists_blockers(self, store):
        plan = self._plan(
            store, generated={"Why?": "I am an AWS Certified Solutions Architect."}
        )
        preview = plan.preview()
        assert "NOT READY TO SUBMIT" in preview
        assert "blocked" in preview

    def test_preview_includes_generated_text(self, store):
        plan = self._plan(store, generated={"Why us?": "I use Python at Northwind Systems."})
        assert "Why us?" in plan.preview()
