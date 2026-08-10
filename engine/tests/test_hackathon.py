"""Tests for hackathon submission drafting (PRD §8.2)."""

import json

import pytest

from haru.adapters.hackathon import (
    SECTION_PROMPTS,
    Section,
    build_prompt,
    draft,
)
from haru.adapters.repo import scan
from haru.brain.fact_boundary import FactBoundary, normalize
from haru.models.providers import EchoProvider
from haru.models.router import ModelRouter
from haru.models.types import Tier


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo-project"\ndependencies = ["fastapi", "pydantic"]\n',
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("import fastapi\n" * 30, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return scan(tmp_path)


BOUNDARY = FactBoundary(
    allowed_skills=frozenset(normalize(t) for t in ("Python", "FastAPI", "Pydantic")),
    preserved_projects=frozenset({normalize("demo-project")}),
)


def router_with(replies: list[str]) -> ModelRouter:
    return ModelRouter(
        {Tier.LOCAL_LARGE: EchoProvider(tier=Tier.LOCAL_LARGE, replies=replies)}
    )


class TestPrompt:
    def test_lists_only_real_technologies(self, project):
        prompt = build_prompt(Section.HOW_WE_BUILT_IT, project)
        assert "fastapi" in prompt
        assert "pydantic" in prompt
        assert "redis" not in prompt.lower()

    def test_forbids_inventing_technology(self, project):
        assert "Do not mention any other tool" in build_prompt(Section.WHAT_IT_DOES, project)

    def test_forbids_inventing_metrics(self, project):
        assert "Do not invent metrics" in build_prompt(Section.ACCOMPLISHMENTS, project)

    def test_includes_real_scale(self, project):
        prompt = build_prompt(Section.ACCOMPLISHMENTS, project)
        assert str(project.file_count) in prompt
        assert "with tests" in prompt

    def test_carries_notes_and_team(self, project):
        prompt = build_prompt(
            Section.INSPIRATION, project, notes="built at a 24h event", team=("Ada",)
        )
        assert "24h event" in prompt
        assert "Ada" in prompt

    def test_every_section_has_an_instruction(self):
        for section in Section:
            assert section in SECTION_PROMPTS


class TestDrafting:
    def test_accepts_a_grounded_draft(self, project):
        router = router_with(["demo-project is built in Python with FastAPI."])
        result = draft(project, router, BOUNDARY, sections=(Section.TAGLINE,))

        drafted = result.sections[Section.TAGLINE]
        assert drafted.is_usable
        assert "FastAPI" in drafted.text

    def test_blocks_an_inflated_draft(self, project):
        router = router_with(
            [
                "demo-project streams through Kafka into Redis.",
                "demo-project streams through Kafka into Redis.",
            ]
        )
        result = draft(project, router, BOUNDARY, sections=(Section.HOW_WE_BUILT_IT,))

        drafted = result.sections[Section.HOW_WE_BUILT_IT]
        assert not drafted.is_usable
        assert {v.term for v in drafted.blocked} >= {"Kafka", "Redis"}

    def test_retries_with_the_violation_fed_back(self, project):
        router = router_with(
            [
                "Built on Redis for caching.",
                "Built in Python with FastAPI.",
            ]
        )
        result = draft(project, router, BOUNDARY, sections=(Section.HOW_WE_BUILT_IT,))
        assert result.sections[Section.HOW_WE_BUILT_IT].is_usable, "the retry should succeed"

    def test_blocked_sections_are_reported_not_dropped(self, project):
        router = router_with(["Uses Kubernetes."] * 4)
        result = draft(
            project, router, BOUNDARY, sections=(Section.TAGLINE, Section.CHALLENGES)
        )
        assert len(result.sections) == 2, "nothing is silently discarded"
        assert len(result.blocked) == 2
        assert not result.is_complete

    def test_complete_submission(self, project):
        router = router_with(["demo-project uses Python and FastAPI."] * 20)
        result = draft(project, router, BOUNDARY)
        assert result.is_complete
        assert set(result.usable) == set(Section)

    def test_declared_team_is_permitted(self, project):
        router = router_with(["Ada and Grace built demo-project in Python."] * 2)
        result = draft(
            project, router, BOUNDARY, sections=(Section.TAGLINE,), team=("Ada", "Grace")
        )
        assert result.sections[Section.TAGLINE].is_usable

    def test_undeclared_names_still_block(self, project):
        router = router_with(["Engineers from Google built demo-project."] * 2)
        result = draft(project, router, BOUNDARY, sections=(Section.TAGLINE,))
        assert not result.sections[Section.TAGLINE].is_usable

    def test_omissions_are_surfaced(self, project):
        router = router_with(["demo-project is written in Python."] * 20)
        result = draft(project, router, BOUNDARY, sections=(Section.TAGLINE,))
        assert any(o.term in {"fastapi", "pydantic"} for o in result.omissions)


class TestPreview:
    def test_shows_sections_and_repo(self, project):
        router = router_with(["demo-project uses Python and FastAPI."] * 20)
        preview = draft(project, router, BOUNDARY, sections=(Section.TAGLINE,)).preview()
        assert "demo-project" in preview
        assert "Tagline" in preview

    def test_shows_why_a_section_was_blocked(self, project):
        router = router_with(["Runs on Kubernetes."] * 4)
        preview = draft(project, router, BOUNDARY, sections=(Section.TAGLINE,)).preview()
        assert "BLOCKED" in preview
        assert "Kubernetes" in preview
