"""Unit tests for the fact-boundary validator (PRD §10.2, M3).

The corpus in ``test_fabrication_corpus.py`` is the acceptance suite. These are
the finer-grained tests: detector behaviour, mode handling, and regressions for
false positives — which matter as much as misses, because a validator that
blocks honest writing gets switched off.
"""

import pytest

from haru.brain.fact_boundary import FactBoundary, normalize
from haru.validation.detect import canonical, find_mentions, find_numeric_claims
from haru.validation.seam import is_stubbed, reset_validator, validate
from haru.validation.types import (
    Artifact,
    ArtifactKind,
    Check,
    Severity,
    ValidationMode,
)
from haru.validation.validator import FactBoundaryValidator, install


def boundary(**kwargs) -> FactBoundary:
    fields = {
        key: frozenset(normalize(t) for t in values)
        for key, values in kwargs.items()
    }
    return FactBoundary(**fields)


BASE = boundary(
    allowed_skills=["Python", "PostgreSQL", "Docker", "FastAPI"],
    preserved_orgs=["Northwind Systems"],
    preserved_projects=["Haru"],
    preserved_institutions=["University of Dhaka"],
    claimable_credentials=["AWS Certified Cloud Practitioner"],
    real_metrics=["40% faster", "3 person team"],
)


@pytest.fixture
def validator():
    return FactBoundaryValidator()


def check(validator, text, b=BASE, mode=ValidationMode.NORMAL):
    return validator.validate(
        Artifact(kind=ArtifactKind.CV_BULLET, text=text), b, mode
    )


class TestClaimDetection:
    def test_owned_skill_passes(self, validator):
        assert check(validator, "Built services with Python and Docker.").passed

    def test_unowned_skill_blocks(self, validator):
        result = check(validator, "Built services with Django.")
        assert not result.passed
        assert result.blocking[0].term == "Django"

    def test_third_party_mention_is_not_a_claim(self, validator):
        assert check(
            validator, "My Docker experience should suit your Kubernetes stack."
        ).passed

    def test_disclaimed_skill_is_not_a_claim(self, validator):
        assert check(
            validator, "I have not worked with Kubernetes, though I use Docker."
        ).passed

    def test_same_term_claimed_elsewhere_still_blocks(self, validator):
        assert not check(validator, "Ran Kubernetes in production.").passed

    def test_owned_org_passes(self, validator):
        assert check(validator, "Worked at Northwind Systems on ingestion.").passed

    def test_unowned_org_blocks(self, validator):
        assert not check(validator, "Worked at Google on ingestion.").passed

    def test_multiword_institution(self, validator):
        assert check(validator, "Studied at the University of Dhaka.").passed

    def test_acronym_at_sentence_start_is_checked(self, validator):
        # "MIT graduate…" — an acronym is a name wherever it sits.
        assert not check(validator, "MIT shaped how I approach systems.").passed

    def test_ordinary_word_at_sentence_start_is_not(self, validator):
        assert check(validator, "Computer science underpins my work.").passed


class TestFalsePositiveRegressions:
    """Each of these was a real defect found by inspecting output."""

    def test_and_does_not_weld_two_entities(self, validator):
        result = check(validator, "Built services in Django and Spring Boot.")
        terms = {v.term for v in result.blocking}
        assert "Django" in terms
        assert "Spring Boot" in terms
        assert not any(t and "and" in t.split() for t in terms)

    def test_bare_job_title_is_not_flagged(self, validator):
        result = check(validator, "Senior Engineer at Google.")
        terms = {v.term for v in result.blocking}
        assert "Google" in terms
        assert "Engineer" not in terms

    def test_job_title_inside_a_credential_name_survives(self, validator):
        result = check(
            validator, "Holds the AWS Certified Solutions Architect credential."
        )
        assert not result.passed
        assert any("Architect" in (v.term or "") for v in result.blocking)

    def test_generic_tech_vocabulary_is_ignored(self, validator):
        assert check(validator, "Built REST APIs in Python returning JSON.").passed

    @pytest.mark.parametrize(
        "text",
        [
            "Served over ASGI with FastAPI.",
            "Streams updates over SSE.",
            "Uses JWT for auth alongside Python.",
            "Reads the DOM with Python.",
        ],
    )
    def test_protocol_and_interface_names_are_not_claims(self, validator, text):
        """Found by a real model: 'built on ASGI' with FastAPI is accurate."""
        assert check(validator, text).passed, text

    def test_spelling_aliases_resolve(self, validator):
        assert check(validator, "Deep experience with postgres and DOCKER.").passed

    def test_years_are_not_treated_as_metrics(self, validator):
        assert check(validator, "Worked at Northwind Systems since 2019.").passed


class TestCredentials:
    """Never stretchable, in any mode."""

    def test_held_credential_passes(self, validator):
        assert check(validator, "AWS Certified Cloud Practitioner.").passed

    def test_different_credential_blocks(self, validator):
        result = check(validator, "AWS Certified Solutions Architect.")
        assert result.blocking[0].check is Check.CREDENTIAL

    def test_vague_credential_claim_blocks(self, validator):
        result = check(validator, "I am a certified cloud professional.")
        assert not result.passed
        assert result.blocking[0].check is Check.CREDENTIAL

    @pytest.mark.parametrize("mode", list(ValidationMode))
    def test_blocks_in_every_mode(self, validator, mode):
        assert not check(
            validator, "AWS Certified Solutions Architect.", mode=mode
        ).passed


class TestMetrics:
    def test_verified_metric_passes(self, validator):
        assert check(validator, "Made the ingestion path 40% faster.").passed

    def test_unverified_metric_blocks(self, validator):
        assert not check(validator, "Cut costs by 85%.").passed

    def test_inflated_metric_blocks(self, validator):
        assert not check(validator, "Made it 400% faster.").passed

    def test_span_matching_finds_multiword_metrics(self):
        claims = find_numeric_claims("Sustained 12000 rows/sec here.")
        spans = claims[0][1]
        assert "12000 rows/sec" in spans


class TestModeHandling:
    CLICHE_TEXT = "A passionate self-starter with a proven track record."

    def test_cliche_warns_in_normal_mode(self, validator):
        result = check(validator, self.CLICHE_TEXT, mode=ValidationMode.NORMAL)
        assert result.passed
        assert result.warnings

    def test_cliche_blocks_in_strict_mode(self, validator):
        result = check(validator, self.CLICHE_TEXT, mode=ValidationMode.STRICT)
        assert not result.passed
        assert result.blocking[0].check is Check.CLICHE

    def test_cliche_ignored_in_lenient_mode(self, validator):
        result = check(validator, self.CLICHE_TEXT, mode=ValidationMode.LENIENT)
        assert result.passed
        assert not result.warnings

    def test_fact_boundary_never_relaxes(self, validator):
        for mode in ValidationMode:
            assert not check(validator, "Expert in Django.", mode=mode).passed


class TestLeakage:
    @pytest.mark.parametrize(
        "text",
        [
            "Here is the revised bullet: built things.",
            "I apologize for the error. Built things.",
            "Note: this was updated.",
            "As an AI, I cannot verify this.",
        ],
    )
    def test_model_self_talk_blocks(self, validator, text):
        result = check(validator, text)
        assert any(v.check is Check.MODEL_LEAKAGE for v in result.blocking)

    def test_ordinary_use_of_note_passes(self, validator):
        assert check(validator, "I note that Northwind Systems is hiring.").passed


class TestEmptyBoundary:
    def test_nothing_may_be_claimed(self, validator):
        result = check(validator, "Built services in Python.", b=FactBoundary())
        assert not result.passed
        assert result.blocking[0].check is Check.FACT_BOUNDARY

    def test_message_explains_why(self, validator):
        result = check(validator, "Anything at all.", b=FactBoundary())
        assert "confirmed" in result.blocking[0].message


class TestNeverClaim:
    def test_user_prohibition_wins(self, validator):
        b = boundary(allowed_skills=["Python", "PHP"])
        b = b.model_copy(update={"never_claim": frozenset({normalize("PHP")})})
        result = validator.validate(
            Artifact(kind=ArtifactKind.CV_BULLET, text="Built things in PHP."),
            b,
            ValidationMode.NORMAL,
        )
        assert not result.passed
        assert "never to claim" in result.blocking[0].message


class TestInstallation:
    def test_install_replaces_the_stub(self):
        reset_validator()
        assert is_stubbed()
        try:
            install()
            assert not is_stubbed()
            result = validate(
                Artifact(kind=ArtifactKind.CV_BULLET, text="Expert in Django."), BASE
            )
            assert not result.passed
            assert not result.stubbed
        finally:
            reset_validator()

    def test_extra_vocabulary_is_honoured(self):
        v = FactBoundaryValidator(extra_known_tech=frozenset({"cobol"}))
        result = v.validate(
            Artifact(kind=ArtifactKind.CV_BULLET, text="Wrote cobol daily."),
            BASE,
            ValidationMode.NORMAL,
        )
        assert not result.passed


class TestDetectHelpers:
    def test_canonical_resolves_aliases(self):
        assert canonical("postgres") == canonical("PostgreSQL")
        assert canonical("k8s") == canonical("Kubernetes")

    def test_mentions_carry_usage(self):
        mentions = {m.text: m for m in find_mentions("I use Docker, not Kubernetes.")}
        assert mentions["Docker"].is_claim
        assert mentions["Kubernetes"].disclaimed
