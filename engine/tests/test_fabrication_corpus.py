"""Runs the adversarial corpus against whatever validator is installed.

While the M0 stub is active these cases are skipped — the stub passes
everything by design, so grading it would be meaningless. When M3 installs a
real validator they light up automatically and become the suite that decides
whether the fact boundary actually works.

The corpus is deliberately versioned before the validator (PRD §17.1, M3 notes).
Adding a case here is cheap; weakening one to make a failing detector pass is
the exact failure mode the ordering exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from haru.brain.fact_boundary import FactBoundary, normalize
from haru.validation.seam import is_stubbed, validate
from haru.validation.types import Artifact, ArtifactKind, Check, ValidationMode

CORPUS_PATH = Path(__file__).parent / "corpus" / "fabrications.json"


@pytest.fixture(autouse=True)
def _real_validator():
    """Grade the M3 validator, not the stub.

    Installed per-test rather than globally so the rest of the suite keeps
    exercising the stubbed-submission interlock.
    """
    from haru.validation.seam import reset_validator, set_validator
    from haru.validation.validator import FactBoundaryValidator

    set_validator(FactBoundaryValidator())
    yield
    reset_validator()


def load_corpus() -> dict:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


CORPUS = load_corpus()


def build_boundary(spec: dict) -> FactBoundary:
    """Normalize the corpus boundary the same way derivation does."""
    def terms(key: str) -> frozenset[str]:
        return frozenset(normalize(t) for t in spec.get(key, []))

    return FactBoundary(
        allowed_skills=terms("allowed_skills"),
        preserved_orgs=terms("preserved_orgs"),
        preserved_projects=terms("preserved_projects"),
        preserved_institutions=terms("preserved_institutions"),
        claimable_credentials=terms("claimable_credentials"),
        real_metrics=terms("real_metrics"),
    )


def case_id(case: dict) -> str:
    return case["id"]


class TestCorpusIntegrity:
    """These run always — the corpus itself must stay well-formed."""

    def test_corpus_loads(self):
        assert CORPUS["cases"], "corpus must not be empty"

    def test_ids_are_unique(self):
        ids = [c["id"] for c in CORPUS["cases"]]
        assert len(ids) == len(set(ids))

    def test_every_case_is_well_formed(self):
        for case in CORPUS["cases"]:
            assert case["expect"] in {"block", "pass"}, case["id"]
            assert case["why"], f"{case['id']} must explain itself"
            ArtifactKind(case["kind"])
            if "check" in case:
                Check(case["check"])
            if "mode" in case:
                ValidationMode(case["mode"])

    def test_block_cases_name_the_check(self):
        for case in CORPUS["cases"]:
            if case["expect"] == "block":
                assert "check" in case, f"{case['id']} must say which check catches it"

    def test_corpus_covers_every_blocking_check(self):
        covered = {c.get("check") for c in CORPUS["cases"] if c["expect"] == "block"}
        for check in (Check.FACT_BOUNDARY, Check.CREDENTIAL, Check.MODEL_LEAKAGE):
            assert check.value in covered, f"no adversarial case for {check.value}"

    def test_corpus_has_honest_controls(self):
        """False positives matter as much as misses."""
        passing = [c for c in CORPUS["cases"] if c["expect"] == "pass"]
        assert len(passing) >= 8, "need enough honest text to catch over-blocking"

    def test_boundary_spec_is_usable(self):
        boundary = build_boundary(CORPUS["boundary"])
        assert not boundary.is_empty
        assert boundary.allows_skill("Python")
        assert not boundary.allows_skill("Rust")


@pytest.mark.parametrize("case", CORPUS["cases"], ids=case_id)
def test_corpus_case(case: dict):
    """The M3 acceptance test. Skipped until a real validator is installed.

    The stub check is made at call time, not collection time — otherwise
    installing the real validator during startup would leave these permanently
    skipped, which is precisely the silent failure this corpus exists to prevent.
    """
    if is_stubbed():
        pytest.skip("validation is stubbed until M3; grading the stub proves nothing")

    spec = (
        {} if case.get("boundary_override") == "empty" else CORPUS["boundary"]
    )
    boundary = build_boundary(spec)
    mode = ValidationMode(case.get("mode", "normal"))
    artifact = Artifact(kind=ArtifactKind(case["kind"]), text=case["text"])

    result = validate(artifact, boundary, mode)

    if case["expect"] == "block":
        assert not result.passed, f"{case['id']} should have been blocked — {case['why']}"
        caught = {v.check.value for v in result.blocking}
        assert case["check"] in caught, (
            f"{case['id']} blocked by {caught}, expected {case['check']}"
        )
    else:
        assert result.passed, (
            f"{case['id']} was blocked but is honest — {case['why']}. "
            f"Violations: {[str(v) for v in result.blocking]}"
        )
