"""Tests for repo scanning and repo-grounded validation (PRD §8.2)."""

import json
from pathlib import Path

import pytest

from haru.adapters.repo import RepoFacts, scan
from haru.brain.fact_boundary import FactBoundary, normalize
from haru.validation.grounding import (
    RepoGroundedValidator,
    claimed_technologies,
    find_omissions,
)
from haru.validation.types import (
    Artifact,
    ArtifactKind,
    Check,
    ValidationMode,
)

ENGINE_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project(tmp_path):
    """A small but realistic Python + JS project."""
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo-project"
dependencies = ["fastapi>=0.100", "pydantic", "uvicorn[standard]>=0.27"]

[project.optional-dependencies]
dev = ["pytest"]
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18"}, "devDependencies": {"vite": "^5"}}),
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\nA demo project.", encoding="utf-8")
    (tmp_path / "app.py").write_text("import fastapi\n" * 20, encoding="utf-8")
    (tmp_path / "ui.ts").write_text("export const x = 1;\n" * 5, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    junk = tmp_path / "node_modules" / "left-pad"
    junk.mkdir(parents=True)
    (junk / "index.js").write_text("module.exports = 1;\n" * 500, encoding="utf-8")

    return scan(tmp_path)


def story(text: str) -> Artifact:
    return Artifact(kind=ArtifactKind.HACKATHON_STORY, text=text)


EMPTY_BOUNDARY_SAFE = FactBoundary(
    allowed_skills=frozenset({normalize(t) for t in ("Python", "TypeScript", "FastAPI", "React")}),
    preserved_projects=frozenset({normalize("demo-project")}),
)


class TestScanning:
    def test_reads_name_from_manifest(self, project):
        assert project.name == "demo-project"

    def test_detects_languages_from_files(self, project):
        assert "python" in project.languages
        assert "typescript" in project.languages

    def test_reads_python_dependencies(self, project):
        assert {"fastapi", "pydantic", "uvicorn"} <= project.dependencies

    def test_strips_version_specifiers_and_extras(self, project):
        assert "uvicorn" in project.dependencies
        assert not any(">" in d or "[" in d for d in project.dependencies)

    def test_reads_optional_dependencies(self, project):
        assert "pytest" in project.dependencies

    def test_reads_node_dependencies(self, project):
        assert {"react", "vite"} <= project.dependencies

    def test_ignores_vendored_code(self, project):
        """node_modules is not the author's work and must not inflate the count."""
        assert project.code_lines < 200
        assert "javascript" not in project.languages

    def test_detects_tests(self, project):
        assert project.has_tests

    def test_reads_readme(self, project):
        assert "A demo project" in project.readme

    def test_records_manifests(self, project):
        assert {"pyproject.toml", "package.json"} <= project.manifests

    def test_supports_is_alias_tolerant(self, project):
        assert project.supports("FastAPI")
        assert project.supports("fastapi")
        assert not project.supports("Django")

    def test_project_name_is_supported(self, project):
        assert project.supports("demo-project")

    def test_missing_repo_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            scan(tmp_path / "nope")

    def test_summary_is_informative(self, project):
        summary = project.summary()
        assert "demo-project" in summary
        assert "has tests" in summary


class TestSelfScan:
    """Scanning this repository — the honest test of a repo scanner."""

    def test_finds_haru(self):
        facts = scan(ENGINE_ROOT)
        assert facts.name == "haru"
        assert "python" in facts.languages
        assert facts.has_tests

    def test_finds_real_dependencies(self):
        facts = scan(ENGINE_ROOT)
        assert {"fastapi", "pydantic", "playwright", "cryptography"} <= facts.dependencies

    def test_does_not_claim_what_haru_lacks(self):
        facts = scan(ENGINE_ROOT)
        for absent in ("django", "redis", "kafka", "kubernetes", "tensorflow"):
            assert not facts.supports(absent)

    def test_excludes_the_virtualenv(self):
        facts = scan(ENGINE_ROOT)
        assert facts.code_lines < 100_000, "site-packages must not be counted"


class TestGroundedValidation:
    def _validate(self, repo, text, boundary=EMPTY_BOUNDARY_SAFE):
        validator = RepoGroundedValidator(repo)
        return validator, validator.validate(story(text), boundary, ValidationMode.NORMAL)

    def test_supported_claim_passes(self, project):
        _, result = self._validate(
            project, "We built demo-project with FastAPI and React."
        )
        assert result.passed, [str(v) for v in result.blocking]

    def test_unsupported_claim_blocks(self, project):
        _, result = self._validate(
            project, "We built demo-project on Redis and Kafka for streaming."
        )
        assert not result.passed
        terms = {v.term for v in result.blocking if v.check is Check.REPO_GROUNDING}
        assert "Redis" in terms
        assert "Kafka" in terms

    def test_message_cites_the_repository(self, project):
        _, result = self._validate(project, "We used Kubernetes throughout.")
        violation = next(v for v in result.blocking if v.check is Check.REPO_GROUNDING)
        assert "does not contain" in violation.message
        assert "demo-project" in violation.message

    def test_grounding_blocks_in_every_mode(self, project):
        for mode in ValidationMode:
            validator = RepoGroundedValidator(project)
            result = validator.validate(story("Built on Redis."), EMPTY_BOUNDARY_SAFE, mode)
            assert not result.passed, mode

    def test_project_name_is_not_flagged(self, project):
        _, result = self._validate(project, "demo-project began as a weekend idea.")
        assert result.passed

    def test_declared_team_and_event_are_allowed(self, project):
        """The user states who and where; only those exact names pass."""
        validator = RepoGroundedValidator(
            project, team=("Ada", "Grace"), event="HackPrinceton"
        )
        result = validator.validate(
            story("Ada and Grace built demo-project at HackPrinceton over one weekend."),
            EMPTY_BOUNDARY_SAFE,
            ValidationMode.NORMAL,
        )
        assert result.passed, [str(v) for v in result.blocking]

    def test_undeclared_names_still_block(self, project):
        """Context widens the boundary only by exactly what the user supplied."""
        validator = RepoGroundedValidator(project, team=("Ada",), event="HackPrinceton")
        result = validator.validate(
            story("Ada built demo-project with engineers from Google."),
            EMPTY_BOUNDARY_SAFE,
            ValidationMode.NORMAL,
        )
        assert not result.passed
        assert any(v.term == "Google" for v in result.blocking)

    def test_context_does_not_leak_into_other_artifacts(self, project):
        validator = RepoGroundedValidator(project, team=("Grace",))
        result = validator.validate(
            Artifact(kind=ArtifactKind.COVER_LETTER, text="I worked at Grace."),
            EMPTY_BOUNDARY_SAFE,
            ValidationMode.NORMAL,
        )
        assert not result.passed, "a cover letter gets no hackathon context"

    def test_a_rejected_alternative_is_not_a_claim(self, project):
        _, result = self._validate(
            project, "We did not use Redis; FastAPI handled it in process."
        )
        assert result.passed

    def test_other_projects_technology_is_not_a_claim(self, project):
        _, result = self._validate(
            project, "Unlike your Kubernetes setup, demo-project runs as one process."
        )
        assert result.passed

    def test_only_hackathon_stories_are_grounded(self, project):
        validator = RepoGroundedValidator(project)
        result = validator.validate(
            Artifact(kind=ArtifactKind.COVER_LETTER, text="I have used Redis."),
            EMPTY_BOUNDARY_SAFE,
            ValidationMode.NORMAL,
        )
        assert not any(v.check is Check.REPO_GROUNDING for v in result.violations)

    def test_fact_boundary_still_applies(self, project):
        """A submission must not claim credentials either."""
        _, result = self._validate(
            project, "As an AWS Certified Solutions Architect I built demo-project."
        )
        assert not result.passed
        assert any(v.check is Check.CREDENTIAL for v in result.blocking)

    def test_model_leakage_still_applies(self, project):
        _, result = self._validate(project, "Here is the revised story: we built it.")
        assert any(v.check is Check.MODEL_LEAKAGE for v in result.blocking)

    def test_without_a_repo_it_is_just_the_fact_boundary(self):
        validator = RepoGroundedValidator(None)
        result = validator.validate(
            story("Built on Redis."), EMPTY_BOUNDARY_SAFE, ValidationMode.NORMAL
        )
        assert not any(v.check is Check.REPO_GROUNDING for v in result.violations)


class TestOmissions:
    """Under-claiming is not dishonest, but it loses earned credit."""

    def test_unmentioned_dependencies_are_surfaced(self, project):
        omissions = find_omissions("We built it with FastAPI.", project)
        terms = {o.term for o in omissions}
        assert "react" in terms or "pydantic" in terms

    def test_mentioned_technology_is_not_an_omission(self, project):
        omissions = find_omissions(
            "Built with FastAPI, pydantic, uvicorn, React, vite, pytest, in Python and TypeScript.",
            project,
        )
        assert not any(o.term in {"fastapi", "react"} for o in omissions)

    def test_omissions_are_not_violations(self, project):
        validator = RepoGroundedValidator(project)
        result = validator.validate(
            story("We built demo-project with FastAPI."), EMPTY_BOUNDARY_SAFE, ValidationMode.NORMAL
        )
        assert result.passed
        assert validator.omissions, "should still be reported as suggestions"

    def test_omission_reads_as_a_suggestion(self, project):
        omissions = find_omissions("We built it.", project)
        assert "not mentioned" in str(omissions[0])

    def test_project_name_is_not_an_omission(self, project):
        """Suggestions are only useful while they stay short and relevant."""
        terms = {o.term for o in find_omissions("We built it.", project)}
        assert "demo-project" not in terms


class TestClaimExtraction:
    def test_finds_claimed_technologies(self):
        claims = {c.lower() for c in claimed_technologies("We used Redis and Python.")}
        assert "redis" in claims
        assert "python" in claims

    def test_skips_generic_vocabulary(self):
        claims = {c.lower() for c in claimed_technologies("We exposed a REST API returning JSON.")}
        assert "rest" not in claims
        assert "json" not in claims

    def test_skips_disclaimed_technology(self):
        assert not any(
            c.lower() == "redis"
            for c in claimed_technologies("We never used Redis.")
        )
