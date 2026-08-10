"""Tests for the Opportunity Inbox (PRD §9)."""

from datetime import date, timedelta

import pytest

from haru.brain.fact_boundary import derive
from haru.brain.models import Experience, Skill
from haru.brain.provenance import Provenance
from haru.brain.store import BrainStore
from haru.discovery.inbox import Inbox, canonical_url
from haru.discovery.opportunity import (
    Kind,
    Source,
    Status,
    classify,
    extract_deadline,
    extract_json_ld,
    from_json_ld,
)

TODAY = date.today()


@pytest.fixture
def inbox():
    return Inbox()


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "brain.sqlite")
    ok = Provenance.entered
    s.put(
        Experience(
            org="Northwind", title="Backend Engineer", provenance=ok(),
            technologies=["Python", "PostgreSQL", "Docker"],
        )
    )
    for name in ("Python", "PostgreSQL", "Docker"):
        s.put(Skill(name=name, provenance=ok(), evidence_refs=["e1"]))
    yield s
    s.close()


class TestClassification:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://boards.greenhouse.io/x/jobs/1", Kind.JOB),
            ("https://jobs.lever.co/x/abc", Kind.JOB),
            ("https://devpost.com/hackathons/foo", Kind.HACKATHON),
            ("https://devfolio.co/x", Kind.HACKATHON),
            ("https://www.gov.uk/apply-passport", Kind.GOVERNMENT_FORM),
        ],
    )
    def test_host_decides_outright(self, url, expected):
        assert classify(url=url) is expected

    def test_host_beats_misleading_prose(self):
        """A Devpost URL is a hackathon whatever the page waffles about."""
        assert classify(
            url="https://devpost.com/software/x",
            text="We are hiring! Full-time role with a benefits package.",
        ) is Kind.HACKATHON

    def test_keywords_used_when_host_is_unknown(self):
        assert classify(
            url="https://example.com/post",
            text="Join our hackathon! Submission deadline Friday, prize track for AI.",
        ) is Kind.HACKATHON

    def test_job_keywords(self):
        assert classify(
            text="Job description. Responsibilities include. Qualifications: 3 years. Full-time."
        ) is Kind.JOB

    def test_unknown_when_nothing_matches(self):
        assert classify(text="A recipe for bread.") is Kind.UNKNOWN


class TestDeadlines:
    def test_iso_date_near_a_cue(self):
        assert extract_deadline("Application deadline: 2026-09-30.") == date(2026, 9, 30)

    def test_written_date(self):
        assert extract_deadline("Closes on 30 September 2026.") == date(2026, 9, 30)

    def test_american_order(self):
        assert extract_deadline("Apply by Sep 30, 2026") == date(2026, 9, 30)

    def test_relative(self):
        assert extract_deadline("3 days left to apply", today=TODAY) == TODAY + timedelta(days=3)

    def test_ignores_dates_with_no_deadline_cue(self):
        """A posting is full of dates; only one is the deadline."""
        assert extract_deadline("Founded 2015-01-01. Start date 2026-01-01.") is None

    def test_picks_the_cued_date_among_several(self):
        text = "Founded 2015-01-01. Apply by 2026-09-30. Start 2027-01-01."
        assert extract_deadline(text) == date(2026, 9, 30)

    def test_no_date(self):
        assert extract_deadline("Apply whenever you like.") is None


class TestJsonLd:
    HTML = """
    <html><head>
    <script type="application/ld+json">
    {"@type":"JobPosting","title":"Backend Engineer",
     "hiringOrganization":{"name":"Northwind Systems"},
     "description":"<p>We need <b>Python</b> and Docker.</p>",
     "validThrough":"2026-09-30T23:59:59Z"}
    </script></head><body>ignored</body></html>
    """

    def test_extracts_job_posting(self):
        assert extract_json_ld(self.HTML)["title"] == "Backend Engineer"

    def test_maps_fields(self):
        mapped = from_json_ld(extract_json_ld(self.HTML))
        assert mapped["org"] == "Northwind Systems"
        assert mapped["deadline"] == date(2026, 9, 30)

    def test_strips_html_from_description(self):
        assert "<b>" not in from_json_ld(extract_json_ld(self.HTML))["text"]

    def test_missing_or_broken_json_ld(self):
        assert extract_json_ld("<html><body>nothing</body></html>") == {}
        assert extract_json_ld('<script type="application/ld+json">{bad</script>') == {}
        assert from_json_ld({}) == {}


class TestCanonicalUrl:
    def test_strips_tracking_parameters(self):
        assert canonical_url("https://x.com/jobs/1?utm_source=newsletter") == canonical_url(
            "https://x.com/jobs/1"
        )

    def test_keeps_meaningful_parameters(self):
        assert "gh_jid=42" in canonical_url("https://x.com/jobs?gh_jid=42")

    def test_normalises_host_scheme_and_slash(self):
        variants = [
            "http://www.x.com/jobs/1/",
            "https://x.com/jobs/1",
            "https://WWW.X.com/jobs/1",
        ]
        assert len({canonical_url(v) for v in variants}) == 1

    def test_empty(self):
        assert canonical_url("") == ""


class TestCapture:
    def test_captures_and_classifies(self, inbox):
        item = inbox.capture(
            url="https://boards.greenhouse.io/northwind/jobs/1",
            title="Backend Engineer",
            text="We need Python. Apply by 2026-09-30.",
        )
        assert item.kind is Kind.JOB
        assert item.deadline == date(2026, 9, 30)
        assert len(inbox) == 1

    def test_json_ld_enriches(self, inbox):
        item = inbox.capture(
            url="https://x.com/jobs/1", html=TestJsonLd.HTML, source=Source.BROWSER_CAPTURE
        )
        assert item.title == "Backend Engineer"
        assert item.org == "Northwind Systems"
        assert item.status is Status.ENRICHED

    def test_capture_from_a_social_post(self, inbox):
        """The long tail no scraper reaches — a friend's group post."""
        item = inbox.capture(
            text="My team is hiring! Job description below. Responsibilities: Python.",
            source=Source.FORWARDED,
            note="from the Dhaka devs group",
        )
        assert item.kind is Kind.JOB
        assert item.source is Source.FORWARDED
        assert "Dhaka" in item.note

    def test_every_source_is_passive(self):
        """None of these require logging into anyone's feed (PRD §9.1)."""
        assert Source.BROWSER_CAPTURE in Source
        assert not any("scrape" in s.value for s in Source)


class TestDeduplication:
    def test_same_url_is_one_item(self, inbox):
        inbox.capture(url="https://x.com/jobs/1", title="Backend Engineer")
        inbox.capture(url="https://x.com/jobs/1?utm_source=twitter", title="Backend Engineer")
        assert len(inbox) == 1

    def test_same_role_and_org_from_different_urls(self, inbox):
        inbox.capture(url="https://board-a.com/1", title="Backend Engineer", org="Northwind")
        inbox.capture(url="https://board-b.com/9", title="Backend Engineer", org="Northwind")
        assert len(inbox) == 1

    def test_different_roles_stay_separate(self, inbox):
        inbox.capture(url="https://x.com/1", title="Backend Engineer", org="Northwind")
        inbox.capture(url="https://x.com/2", title="Frontend Engineer", org="Northwind")
        assert len(inbox) == 2

    def test_merge_keeps_the_richer_sighting(self, inbox):
        inbox.capture(url="https://x.com/jobs/1", title="Backend Engineer", text="short")
        item = inbox.capture(
            url="https://x.com/jobs/1", text="a much longer and more useful description"
        )
        assert "much longer" in item.text
        assert item.title == "Backend Engineer", "existing detail is not lost"

    def test_merge_fills_a_missing_deadline(self, inbox):
        inbox.capture(url="https://x.com/jobs/1", title="Role")
        item = inbox.capture(url="https://x.com/jobs/1", text="Deadline: 2026-09-30")
        assert item.deadline == date(2026, 9, 30)

    def test_already_applied_guard(self, inbox):
        item = inbox.capture(url="https://x.com/jobs/1", title="Role")
        assert not inbox.already_applied("https://x.com/jobs/1")
        inbox.mark_applied(item.id)
        assert inbox.already_applied("https://x.com/jobs/1?utm_source=x")


class TestScoring:
    def test_scores_against_the_brain(self, inbox, store):
        inbox.capture(
            url="https://x.com/jobs/1", title="Backend Engineer",
            text="We need Python, PostgreSQL and Docker.",
        )
        inbox.score_all(derive(store))
        assert inbox.all()[0].fit_score == 1.0

    def test_reports_what_is_missing(self, inbox, store):
        inbox.capture(url="https://x.com/jobs/1", text="We need Python and Kubernetes.")
        inbox.score_all(derive(store))
        assert any(m.lower() == "kubernetes" for m in inbox.all()[0].missing)

    def test_scoring_is_idempotent(self, inbox, store):
        inbox.capture(url="https://x.com/jobs/1", text="Python required.")
        inbox.score_all(derive(store))
        first = inbox.all()[0].fit_score
        inbox.score_all(derive(store))
        assert inbox.all()[0].fit_score == first


class TestQueue:
    def test_urgent_deadlines_come_first(self, inbox):
        inbox.capture(url="https://x.com/1", title="Later", text=f"Deadline: {TODAY + timedelta(days=40)}")
        inbox.capture(url="https://x.com/2", title="Soon", text=f"Deadline: {TODAY + timedelta(days=2)}")
        assert inbox.queue()[0].title == "Soon"

    def test_expired_items_are_hidden(self, inbox):
        inbox.capture(url="https://x.com/1", title="Gone", text=f"Deadline: {TODAY - timedelta(days=1)}")
        assert inbox.queue() == []
        assert len(inbox.queue(include_expired=True)) == 1

    def test_dismissed_items_leave_the_queue(self, inbox):
        item = inbox.capture(url="https://x.com/1", title="Nope")
        inbox.dismiss(item.id, note="not interested")
        assert inbox.queue() == []
        assert inbox.get(item.id).note == "not interested"

    def test_applied_items_leave_the_queue(self, inbox):
        item = inbox.capture(url="https://x.com/1", title="Done")
        inbox.mark_applied(item.id)
        assert inbox.queue() == []

    def test_filter_by_kind(self, inbox):
        inbox.capture(url="https://boards.greenhouse.io/1", title="Job")
        inbox.capture(url="https://devpost.com/h/1", title="Hack")
        assert len(inbox.queue(kind=Kind.HACKATHON)) == 1

    def test_filter_by_fit(self, inbox, store):
        inbox.capture(url="https://x.com/1", title="Good", text="Python and Docker.")
        inbox.capture(url="https://x.com/2", title="Poor", text="COBOL and Fortran.")
        inbox.score_all(derive(store))
        titles = {o.title for o in inbox.queue(min_fit=0.5)}
        assert titles == {"Good"}

    def test_expiring_soon(self, inbox):
        inbox.capture(url="https://x.com/1", title="Soon", text=f"Deadline: {TODAY + timedelta(days=1)}")
        inbox.capture(url="https://x.com/2", title="Later", text=f"Deadline: {TODAY + timedelta(days=30)}")
        assert [o.title for o in inbox.expiring()] == ["Soon"]

    def test_counts_by_kind(self, inbox):
        inbox.capture(url="https://boards.greenhouse.io/1", title="A")
        inbox.capture(url="https://devpost.com/h/1", title="B")
        assert inbox.counts() == {"job": 1, "hackathon": 1}


class TestNoAutoSubmit:
    """PRD §9.3 — discovery fills a queue; a human decides."""

    def test_captured_items_are_never_applied(self, inbox):
        item = inbox.capture(url="https://x.com/1", title="Role", text="Python.")
        assert item.status is not Status.APPLIED

    def test_scoring_does_not_advance_past_scored(self, inbox, store):
        inbox.capture(url="https://x.com/1", text="Python.")
        inbox.score_all(derive(store))
        assert inbox.all()[0].status is Status.SCORED

    def test_applying_is_an_explicit_call(self, inbox):
        item = inbox.capture(url="https://x.com/1", title="Role")
        assert not inbox.already_applied(item.url)
        inbox.mark_applied(item.id)
        assert inbox.already_applied(item.url)
