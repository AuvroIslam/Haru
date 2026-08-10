"""Tests for the CV engine (PRD §11).

The requirement being verified: *"cv style same, just projects in and out and
heading or whatever will be changed."* So the load-bearing tests are the ones
proving style never moves while content does.
"""

import pytest

from haru.brain.models import (
    Credential,
    Education,
    Experience,
    Identity,
    Project,
    Skill,
)
from haru.brain.provenance import Attested, Provenance, Source
from haru.brain.store import BrainStore
from haru.cv.diff import ChangeKind, diff, summarize
from haru.cv.models import Ask, CVTemplate, Section, Slot, Style
from haru.cv.render import render_html, render_pdf, style_css, write_html
from haru.cv.tailor import score, tailor


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "brain.sqlite")
    yield s
    s.close()


def confirmed() -> Provenance:
    return Provenance.entered()


def imported() -> Provenance:
    return Provenance.create(Source.CV_IMPORT)


@pytest.fixture
def populated(store):
    store.put_singleton(
        Identity(
            legal_name=Attested.entered("Ada Lovelace"),
            emails=[Attested.entered("ada@example.com")],
            city=Attested.entered("London"),
        )
    )
    store.put(
        Experience(
            org="Northwind",
            title="Backend Engineer",
            provenance=confirmed(),
            summary="Owned the ingestion service.",
            technologies=["Python", "PostgreSQL"],
            achievements=[{"text": "Cut latency", "metric": "40%", "verified": True}],
        )
    )
    store.put(
        Experience(
            org="Cedar",
            title="Data Analyst",
            provenance=confirmed(),
            technologies=["JavaScript", "D3"],
        )
    )
    store.put(
        Project(
            name="Haru",
            provenance=confirmed(),
            tagline="Local-first form agent",
            technologies=["Python", "SQLite"],
        )
    )
    store.put(
        Project(
            name="Chartkit",
            provenance=confirmed(),
            technologies=["JavaScript", "D3"],
        )
    )
    store.put(Skill(name="Python", provenance=confirmed(), evidence_refs=["e1"]))
    store.put(Skill(name="D3", provenance=confirmed(), evidence_refs=["p2"]))
    store.put(Skill(name="Rust", provenance=confirmed()))  # no evidence
    store.put(Education(institution="University of Dhaka", degree="BSc", provenance=confirmed()))
    store.put(
        Credential(name="AWS CP", provenance=confirmed(), document_ref="d1")
    )
    store.put(Credential(name="Unevidenced", provenance=confirmed()))
    return store


BACKEND = Ask(role="Backend Engineer", requirements=("Python", "PostgreSQL"))
FRONTEND = Ask(role="Frontend Engineer", requirements=("JavaScript", "D3"))


class TestScoring:
    def test_full_coverage(self):
        value, matched = score(["Python", "PostgreSQL"], BACKEND)
        assert value == 1.0
        assert set(matched) == {"Python", "PostgreSQL"}

    def test_partial_coverage(self):
        value, matched = score(["Python"], BACKEND)
        assert value == 0.5
        assert matched == ("Python",)

    def test_no_coverage(self):
        assert score(["COBOL"], BACKEND) == (0.0, ())

    def test_empty_ask_scores_zero(self):
        assert score(["Python"], Ask()) == (0.0, ())

    def test_normalisation_matches_fact_boundary(self):
        value, _ = score(["node.js"], Ask(requirements=("NodeJS",)))
        assert value == 1.0

    def test_long_tech_lists_do_not_dominate(self):
        # Coverage of the requirement, not raw match count.
        few, _ = score(["Python", "PostgreSQL"], BACKEND)
        many, _ = score(["Python", "PostgreSQL"] + [f"x{i}" for i in range(50)], BACKEND)
        assert few == many == 1.0


class TestSelection:
    def test_only_confirmed_content_appears(self, store):
        store.put(Project(name="Pending", provenance=imported()))
        store.put(Project(name="Confirmed", provenance=confirmed()))
        cv = tailor(store, CVTemplate(), BACKEND)
        titles = {i.title for i in cv.section_for(Slot.PROJECTS).items}
        assert titles == {"Confirmed"}

    def test_relevant_items_rank_first(self, populated):
        cv = tailor(populated, CVTemplate(), BACKEND)
        assert cv.section_for(Slot.EXPERIENCE).items[0].subtitle == "Northwind"

    def test_a_different_ask_reorders(self, populated):
        cv = tailor(populated, CVTemplate(), FRONTEND)
        assert cv.section_for(Slot.PROJECTS).items[0].title == "Chartkit"

    def test_max_items_truncates(self, populated):
        template = CVTemplate(
            sections=[Section(slot=Slot.PROJECTS, heading="Projects", max_items=1)]
        )
        assert len(tailor(populated, template, BACKEND).section_for(Slot.PROJECTS).items) == 1

    def test_skills_need_evidence(self, populated):
        names = {i.title for i in tailor(populated, CVTemplate(), BACKEND).section_for(Slot.SKILLS).items}
        assert "Python" in names
        assert "Rust" not in names, "unevidenced skill must not reach a CV"

    def test_unevidenced_credential_is_excluded(self, populated):
        names = {i.title for i in tailor(populated, CVTemplate(), BACKEND).section_for(Slot.CREDENTIALS).items}
        assert names == {"AWS CP"}

    def test_selection_records_why(self, populated):
        item = tailor(populated, CVTemplate(), BACKEND).section_for(Slot.EXPERIENCE).items[0]
        assert "Python" in item.reason

    def test_empty_sections_are_dropped(self, store):
        cv = tailor(store, CVTemplate(), BACKEND)
        assert cv.sections == ()

    def test_disabled_sections_are_skipped(self, populated):
        template = CVTemplate(
            sections=[
                Section(slot=Slot.PROJECTS, heading="Projects"),
                Section(slot=Slot.SKILLS, heading="Skills", enabled=False),
            ]
        )
        cv = tailor(populated, template, BACKEND)
        assert cv.section_for(Slot.SKILLS) is None


class TestStyleStability:
    """The core requirement: design never changes, content does."""

    def test_style_is_identical_across_targets(self, populated):
        a = tailor(populated, CVTemplate(), BACKEND)
        b = tailor(populated, CVTemplate(), FRONTEND)
        assert a.style == b.style

    def test_css_is_byte_identical_across_targets(self, populated):
        template = CVTemplate()
        a = tailor(populated, template, BACKEND)
        b = tailor(populated, template, FRONTEND)
        assert style_css(a.style) == style_css(b.style)

    def test_content_does_differ(self, populated):
        template = CVTemplate()
        a = tailor(populated, template, BACKEND)
        b = tailor(populated, template, FRONTEND)
        assert a.section_for(Slot.PROJECTS).items[0].title != b.section_for(
            Slot.PROJECTS
        ).items[0].title

    def test_tailoring_does_not_mutate_the_template(self, populated):
        template = CVTemplate(style=Style(accent_color="#004488"))
        before = template.model_dump()
        tailor(populated, template, BACKEND)
        assert template.model_dump() == before

    def test_custom_style_is_carried_through(self, populated):
        template = CVTemplate(style=Style(font_family="Inter", accent_color="#004488"))
        cv = tailor(populated, template, BACKEND)
        assert cv.style.font_family == "Inter"
        assert "#004488" in style_css(cv.style)

    def test_section_order_follows_the_template(self, populated):
        template = CVTemplate(
            sections=[
                Section(slot=Slot.SKILLS, heading="Skills"),
                Section(slot=Slot.PROJECTS, heading="Projects"),
            ]
        )
        cv = tailor(populated, template, BACKEND)
        assert [s.slot for s in cv.sections] == [Slot.SKILLS, Slot.PROJECTS]

    def test_headings_are_renameable(self, populated):
        template = CVTemplate(
            sections=[Section(slot=Slot.PROJECTS, heading="Selected Work")]
        )
        cv = tailor(populated, template, BACKEND)
        assert cv.section_for(Slot.PROJECTS).heading == "Selected Work"


class TestSummary:
    def test_built_from_confirmed_facts(self, populated):
        text = tailor(populated, CVTemplate(), BACKEND).section_for(Slot.SUMMARY).text
        assert "Northwind" in text

    def test_leads_with_the_most_relevant_role(self, populated):
        """A summary that opens with the wrong role undoes the tailoring."""
        backend = tailor(populated, CVTemplate(), BACKEND).section_for(Slot.SUMMARY).text
        frontend = tailor(populated, CVTemplate(), FRONTEND).section_for(Slot.SUMMARY).text
        assert backend.startswith("Backend Engineer at Northwind")
        assert frontend.startswith("Data Analyst at Cedar")

    def test_sentences_are_well_formed(self, populated):
        text = tailor(populated, CVTemplate(), BACKEND).section_for(Slot.SUMMARY).text
        assert text.endswith(".")
        for sentence in (s.strip() for s in text.split(".") if s.strip()):
            assert sentence[0].isupper(), f"sentence not capitalised: {sentence!r}"

    def test_absent_when_brain_is_empty(self, store):
        assert tailor(store, CVTemplate(), BACKEND).section_for(Slot.SUMMARY) is None

    def test_passes_through_the_validation_seam(self, populated):
        from haru.validation.seam import ObservationLog, PassThroughValidator, reset_validator, set_validator

        obs = ObservationLog()
        set_validator(PassThroughValidator(obs))
        try:
            tailor(populated, CVTemplate(), BACKEND)
            kinds = {o["kind"] for o in obs.observations}
            assert "cv_summary" in kinds
        finally:
            reset_validator()


class TestHeader:
    def test_name_and_contact(self, populated):
        cv = tailor(populated, CVTemplate(), BACKEND)
        assert cv.display_name == "Ada Lovelace"
        assert "ada@example.com" in cv.contact_lines

    def test_missing_identity_is_tolerated(self, store):
        store.put(Project(name="Haru", provenance=confirmed()))
        cv = tailor(store, CVTemplate(), BACKEND)
        assert cv.display_name == ""


class TestDiff:
    def test_no_changes_between_identical_cvs(self, populated):
        template = CVTemplate()
        a = tailor(populated, template, BACKEND)
        assert diff(a, tailor(populated, template, BACKEND)) == []

    def test_detects_added_and_removed_items(self, populated):
        template = CVTemplate(
            sections=[Section(slot=Slot.PROJECTS, heading="Projects", max_items=1)]
        )
        master = tailor(populated, template, BACKEND)
        tailored = tailor(populated, template, FRONTEND)

        changes = diff(master, tailored)
        kinds = {c.kind for c in changes}
        assert ChangeKind.ITEM_ADDED in kinds
        assert ChangeKind.ITEM_REMOVED in kinds

    def test_changes_carry_attribution(self, populated):
        template = CVTemplate(
            sections=[Section(slot=Slot.PROJECTS, heading="Projects", max_items=1)]
        )
        changes = diff(
            tailor(populated, template, BACKEND), tailor(populated, template, FRONTEND)
        )
        added = next(c for c in changes if c.kind is ChangeKind.ITEM_ADDED)
        assert "D3" in added.reason

    def test_detects_heading_rename(self, populated):
        a = tailor(populated, CVTemplate(sections=[Section(slot=Slot.PROJECTS, heading="Projects")]), BACKEND)
        b = tailor(populated, CVTemplate(sections=[Section(slot=Slot.PROJECTS, heading="Selected Work")]), BACKEND)
        change = next(c for c in diff(a, b) if c.kind is ChangeKind.HEADING_CHANGED)
        assert "Selected Work" in change.description

    def test_detects_reordering(self, populated):
        template = CVTemplate(sections=[Section(slot=Slot.PROJECTS, heading="Projects")])
        changes = diff(
            tailor(populated, template, BACKEND), tailor(populated, template, FRONTEND)
        )
        assert any(c.kind is ChangeKind.ITEM_REORDERED for c in changes)

    def test_detects_section_removal(self, populated):
        full = tailor(populated, CVTemplate(), BACKEND)
        trimmed = tailor(
            populated, CVTemplate(sections=[Section(slot=Slot.PROJECTS, heading="Projects")]), BACKEND
        )
        kinds = {c.kind for c in diff(full, trimmed)}
        assert ChangeKind.SECTION_REMOVED in kinds

    def test_summarize_empty(self):
        assert "No changes" in summarize([])

    def test_summarize_counts(self, populated):
        template = CVTemplate(
            sections=[Section(slot=Slot.PROJECTS, heading="Projects", max_items=1)]
        )
        text = summarize(diff(tailor(populated, template, BACKEND), tailor(populated, template, FRONTEND)))
        assert "item added" in text


class TestRender:
    def test_produces_a_document(self, populated):
        html = render_html(tailor(populated, CVTemplate(), BACKEND))
        assert html.startswith("<!doctype html>")
        assert "Ada Lovelace" in html

    def test_includes_headings_and_content(self, populated):
        html = render_html(tailor(populated, CVTemplate(), BACKEND))
        assert "Experience" in html
        assert "Northwind" in html
        assert "Cut latency" in html

    def test_escapes_user_content(self, store):
        store.put_singleton(Identity(legal_name=Attested.entered("<script>alert(1)</script>")))
        store.put(Project(name="Haru", provenance=confirmed()))
        html = render_html(tailor(store, CVTemplate(), BACKEND))
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_style_appears_in_css(self, populated):
        cv = tailor(populated, CVTemplate(style=Style(body_size_pt=11.0)), BACKEND)
        assert "11.0pt" in render_html(cv)

    def test_writes_to_disk(self, populated, tmp_path):
        path = write_html(tailor(populated, CVTemplate(), BACKEND), tmp_path / "out" / "cv.html")
        assert path.exists()
        assert "Ada Lovelace" in path.read_text(encoding="utf-8")

    def test_pdf_fails_loudly_rather_than_silently_differing(self, populated, tmp_path):
        with pytest.raises(NotImplementedError, match="M2"):
            render_pdf(tailor(populated, CVTemplate(), BACKEND), tmp_path / "cv.pdf")
