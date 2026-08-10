"""Tests for fact boundary derivation (PRD §10.2).

The boundary decides what may truthfully be claimed. Everything here is about
what must be *excluded* — a boundary that is too wide is the failure mode that
puts a fabrication on a real application.
"""

import pytest

from haru.brain.fact_boundary import (
    FactBoundary,
    FactBoundaryOverrides,
    derive,
    normalize,
)
from haru.brain.models import Credential, Education, Experience, Project, Skill
from haru.brain.provenance import Provenance, Source
from haru.brain.store import BrainStore


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "brain.sqlite")
    yield s
    s.close()


def imported() -> Provenance:
    return Provenance.create(Source.CV_IMPORT)


def confirmed() -> Provenance:
    return Provenance.entered()


class TestNormalize:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("Node.js", "nodejs"),
            ("node js", "NodeJS"),
            ("  Python  ", "python"),
            ("PostgreSQL", "postgresql"),
            ("CI/CD", "cicd"),
        ],
    )
    def test_equivalent_spellings_fold_together(self, a, b):
        assert normalize(a) == normalize(b)

    def test_plus_and_hash_survive(self):
        # Otherwise "C++" and "C#" both collapse to "c" and the boundary
        # would authorise claiming C from a C++ project.
        assert normalize("C++") != normalize("C")
        assert normalize("C#") != normalize("C")
        assert normalize("C++") != normalize("C#")

    def test_empty_input(self):
        assert normalize("   ") == ""


class TestConfirmationGate:
    """PRD §6.3 — unconfirmed facts never widen the boundary."""

    def test_unconfirmed_project_excluded(self, store):
        store.put(Project(name="Haru", provenance=imported()))
        assert not derive(store).allows_project("Haru")

    def test_confirmed_project_included(self, store):
        store.put(Project(name="Haru", provenance=confirmed()))
        assert derive(store).allows_project("Haru")

    def test_unconfirmed_experience_excluded(self, store):
        store.put(Experience(org="Acme", title="Dev", provenance=imported()))
        assert not derive(store).allows_org("Acme")

    def test_unconfirmed_education_excluded(self, store):
        store.put(Education(institution="MIT", provenance=imported()))
        assert not derive(store).allows_institution("MIT")

    def test_confirming_later_widens_the_boundary(self, store):
        p = store.put(Project(name="Haru", provenance=imported()))
        assert not derive(store).allows_project("Haru")
        store.put(p.model_copy(update={"provenance": p.provenance.confirm()}))
        assert derive(store).allows_project("Haru")


class TestSkillEvidence:
    """A skill with no evidence is an assertion, not a fact."""

    def test_confirmed_skill_without_evidence_excluded(self, store):
        store.put(Skill(name="Rust", provenance=confirmed()))
        assert not derive(store).allows_skill("Rust")

    def test_confirmed_skill_with_evidence_included(self, store):
        store.put(
            Skill(name="Python", provenance=confirmed(), evidence_refs=["p1"])
        )
        assert derive(store).allows_skill("Python")

    def test_technologies_on_confirmed_work_count(self, store):
        store.put(
            Project(
                name="Haru", provenance=confirmed(), technologies=["SQLite", "Pydantic"]
            )
        )
        b = derive(store)
        assert b.allows_skill("SQLite")
        assert b.allows_skill("pydantic")

    def test_technologies_on_unconfirmed_work_do_not(self, store):
        store.put(
            Project(name="Haru", provenance=imported(), technologies=["Kubernetes"])
        )
        assert not derive(store).allows_skill("Kubernetes")


class TestCredentials:
    """PRD §10.2 — certifications are never stretchable."""

    def test_confirmed_without_document_excluded(self, store):
        store.put(Credential(name="AWS Solutions Architect", provenance=confirmed()))
        assert not derive(store).allows_credential("AWS Solutions Architect")

    def test_document_without_confirmation_excluded(self, store):
        store.put(
            Credential(
                name="AWS Solutions Architect",
                provenance=imported(),
                document_ref="d1",
            )
        )
        assert not derive(store).allows_credential("AWS Solutions Architect")

    def test_confirmed_with_document_included(self, store):
        store.put(
            Credential(
                name="AWS Solutions Architect",
                provenance=confirmed(),
                document_ref="d1",
            )
        )
        assert derive(store).allows_credential("AWS Solutions Architect")

    def test_credential_does_not_leak_into_skills(self, store):
        store.put(
            Credential(name="CKA", provenance=confirmed(), document_ref="d1")
        )
        b = derive(store)
        assert b.allows_credential("CKA")
        assert not b.allows_skill("CKA")


class TestMetrics:
    """Only verified numbers may be cited."""

    def test_unverified_metric_excluded(self, store):
        store.put(
            Experience(
                org="Acme",
                title="Dev",
                provenance=confirmed(),
                achievements=[{"text": "Sped things up", "metric": "10x"}],
            )
        )
        assert not derive(store).allows_metric("10x")

    def test_verified_metric_included(self, store):
        store.put(
            Experience(
                org="Acme",
                title="Dev",
                provenance=confirmed(),
                achievements=[
                    {"text": "Sped things up", "metric": "10x", "verified": True}
                ],
            )
        )
        assert derive(store).allows_metric("10x")

    def test_project_outcomes_contribute(self, store):
        store.put(
            Project(
                name="Haru",
                provenance=confirmed(),
                outcomes=[{"text": "Users", "metric": "5000 users", "verified": True}],
            )
        )
        assert derive(store).allows_metric("5000 users")


class TestNeverClaim:
    """User-set prohibitions override every allowance."""

    def test_override_beats_confirmed_fact(self, store):
        store.put(
            Project(name="Haru", provenance=confirmed(), technologies=["PHP"])
        )
        store.put_singleton(FactBoundaryOverrides(never_claim=["PHP"]))

        b = derive(store)
        assert b.is_forbidden("PHP")
        assert not b.allows_skill("PHP")

    def test_override_is_normalized(self, store):
        store.put(
            Project(name="Haru", provenance=confirmed(), technologies=["Node.js"])
        )
        store.put_singleton(FactBoundaryOverrides(never_claim=["nodejs"]))
        assert not derive(store).allows_skill("Node.js")

    def test_unrelated_terms_unaffected(self, store):
        store.put(
            Project(
                name="Haru", provenance=confirmed(), technologies=["PHP", "Python"]
            )
        )
        store.put_singleton(FactBoundaryOverrides(never_claim=["PHP"]))
        b = derive(store)
        assert not b.allows_skill("PHP")
        assert b.allows_skill("Python")


class TestEmptyBoundary:
    def test_fresh_brain_is_empty(self, store):
        assert derive(store).is_empty

    def test_empty_boundary_allows_nothing(self, store):
        b = derive(store)
        assert not b.allows_skill("Python")
        assert not b.allows_org("Acme")
        assert not b.allows_credential("CKA")

    def test_one_confirmed_fact_is_not_empty(self, store):
        store.put(Project(name="Haru", provenance=confirmed()))
        assert not derive(store).is_empty

    def test_unconfirmed_data_still_counts_as_empty(self, store):
        store.put(Project(name="Haru", provenance=imported()))
        assert derive(store).is_empty, "imports alone must not authorise generation"


class TestBoundaryObject:
    def test_is_immutable(self):
        b = FactBoundary()
        with pytest.raises(Exception):
            b.allowed_skills = frozenset({"anything"})

    def test_blank_terms_rejected(self, store):
        store.put(Project(name="Haru", provenance=confirmed()))
        b = derive(store)
        assert not b.allows_skill("")
        assert not b.allows_skill("   ")

    def test_profile_scoped(self, store):
        store.put(Project(name="Industry", provenance=confirmed(), profile_id="a"))
        store.put(Project(name="Academic", provenance=confirmed(), profile_id="b"))

        assert derive(store, profile_id="a").allows_project("Industry")
        assert not derive(store, profile_id="a").allows_project("Academic")

    def test_overrides_are_profile_scoped(self, store):
        store.put(Project(name="X", provenance=confirmed(), profile_id="a", technologies=["PHP"]))
        store.put(Project(name="Y", provenance=confirmed(), profile_id="b", technologies=["PHP"]))
        store.put_singleton(FactBoundaryOverrides(profile_id="a", never_claim=["PHP"]))

        assert not derive(store, profile_id="a").allows_skill("PHP")
        assert derive(store, profile_id="b").allows_skill("PHP")
