"""Tests for the validation seam and severity policy (PRD §10.2, §17.1)."""

import json

import pytest

from haru.brain.fact_boundary import FactBoundary
from haru.validation.seam import (
    ObservationLog,
    PassThroughValidator,
    get_validator,
    is_stubbed,
    reset_validator,
    set_validator,
    validate,
)
from haru.validation.types import (
    UNRELAXABLE,
    Artifact,
    ArtifactKind,
    Check,
    FactBoundaryViolation,
    Result,
    Severity,
    ValidationMode,
    Violation,
    severity_for,
)


@pytest.fixture(autouse=True)
def _clean_validator():
    reset_validator()
    yield
    reset_validator()


def artifact(text: str = "Built a thing.") -> Artifact:
    return Artifact(kind=ArtifactKind.CV_BULLET, text=text)


class TestSeverityPolicy:
    """The policy that M3 must not be able to weaken."""

    @pytest.mark.parametrize("check", sorted(UNRELAXABLE, key=lambda c: c.value))
    @pytest.mark.parametrize("mode", list(ValidationMode))
    def test_unrelaxable_checks_block_in_every_mode(self, check, mode):
        assert severity_for(check, mode) is Severity.BLOCKING

    def test_fact_boundary_blocks_even_in_lenient(self):
        assert severity_for(Check.FACT_BOUNDARY, ValidationMode.LENIENT) is Severity.BLOCKING

    def test_credentials_block_even_in_lenient(self):
        # "No exceptions, no modes."
        assert severity_for(Check.CREDENTIAL, ValidationMode.LENIENT) is Severity.BLOCKING

    def test_cliche_is_the_only_softenable_check(self):
        assert severity_for(Check.CLICHE, ValidationMode.STRICT) is Severity.BLOCKING
        assert severity_for(Check.CLICHE, ValidationMode.NORMAL) is Severity.WARNING
        assert severity_for(Check.CLICHE, ValidationMode.LENIENT) is Severity.IGNORED

    def test_every_check_has_a_policy(self):
        for check in Check:
            for mode in ValidationMode:
                assert isinstance(severity_for(check, mode), Severity)


class TestResult:
    def test_passes_with_no_violations(self):
        r = Result(artifact=artifact(), mode=ValidationMode.NORMAL)
        assert r.passed
        assert r.blocking == ()

    def test_warnings_do_not_block(self):
        r = Result(
            artifact=artifact(),
            mode=ValidationMode.NORMAL,
            violations=(
                Violation(
                    check=Check.CLICHE, severity=Severity.WARNING, message="cliché"
                ),
            ),
        )
        assert r.passed
        assert len(r.warnings) == 1

    def test_blocking_violation_fails(self):
        r = Result(
            artifact=artifact(),
            mode=ValidationMode.NORMAL,
            violations=(
                Violation(
                    check=Check.FACT_BOUNDARY,
                    severity=Severity.BLOCKING,
                    message="unowned skill",
                    term="Kubernetes",
                ),
            ),
        )
        assert not r.passed
        assert len(r.blocking) == 1

    def test_raise_if_blocked_is_quiet_when_passing(self):
        Result(artifact=artifact(), mode=ValidationMode.NORMAL).raise_if_blocked()

    def test_raise_if_blocked_carries_detail(self):
        r = Result(
            artifact=artifact(),
            mode=ValidationMode.NORMAL,
            violations=(
                Violation(
                    check=Check.CREDENTIAL,
                    severity=Severity.BLOCKING,
                    message="no supporting document",
                    term="AWS SA",
                ),
            ),
        )
        with pytest.raises(FactBoundaryViolation) as exc:
            r.raise_if_blocked()
        assert "AWS SA" in str(exc.value)
        assert exc.value.result is r


class TestPassThroughStub:
    def test_stub_is_installed_by_default(self):
        assert is_stubbed()
        assert isinstance(get_validator(), PassThroughValidator)

    def test_stub_passes_everything(self):
        r = validate(artifact("I am a certified Kubernetes wizard."), FactBoundary())
        assert r.passed
        assert r.stubbed

    def test_stub_records_observations(self):
        obs = ObservationLog()
        set_validator(PassThroughValidator(obs))

        validate(artifact("first"), FactBoundary())
        validate(artifact("second"), FactBoundary())

        assert [o["text"] for o in obs.observations] == ["first", "second"]

    def test_observation_captures_boundary_state(self):
        obs = ObservationLog()
        set_validator(PassThroughValidator(obs))
        boundary = FactBoundary(allowed_skills=frozenset({"python", "sqlite"}))

        validate(artifact(), boundary)

        entry = obs.observations[0]
        assert entry["boundary_sizes"]["skills"] == 2
        assert entry["boundary_empty"] is False

    def test_observation_notes_empty_boundary(self):
        obs = ObservationLog()
        set_validator(PassThroughValidator(obs))
        validate(artifact(), FactBoundary())
        assert obs.observations[0]["boundary_empty"] is True

    def test_observations_persist_as_jsonl(self, tmp_path):
        path = tmp_path / "logs" / "seam.jsonl"
        obs = ObservationLog(path)
        set_validator(PassThroughValidator(obs))

        validate(artifact("one"), FactBoundary())
        validate(artifact("two"), FactBoundary())

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["text"] == "one"
        assert json.loads(lines[1])["kind"] == ArtifactKind.CV_BULLET.value

    def test_stub_warns_once(self, caplog):
        set_validator(PassThroughValidator())
        with caplog.at_level("WARNING"):
            validate(artifact(), FactBoundary())
            validate(artifact(), FactBoundary())
        stub_warnings = [r for r in caplog.records if "STUBBED" in r.message]
        assert len(stub_warnings) == 1


class TestValidatorSwapping:
    """M3 must be a drop-in: swapping the validator changes behaviour, not callers."""

    def test_installing_a_real_validator_changes_outcomes(self):
        class Blocker:
            def validate(self, artifact, boundary, mode=ValidationMode.NORMAL):
                return Result(
                    artifact=artifact,
                    mode=mode,
                    violations=(
                        Violation(
                            check=Check.FACT_BOUNDARY,
                            severity=Severity.BLOCKING,
                            message="not in boundary",
                            term="Kubernetes",
                        ),
                    ),
                )

        set_validator(Blocker())
        result = validate(artifact("Expert in Kubernetes."), FactBoundary())

        assert not result.passed
        assert not result.stubbed
        assert not is_stubbed()

    def test_set_validator_returns_previous(self):
        original = get_validator()

        class Noop:
            def validate(self, artifact, boundary, mode=ValidationMode.NORMAL):
                return Result(artifact=artifact, mode=mode)

        previous = set_validator(Noop())
        assert previous is original

    def test_reset_restores_the_stub(self):
        class Noop:
            def validate(self, artifact, boundary, mode=ValidationMode.NORMAL):
                return Result(artifact=artifact, mode=mode)

        set_validator(Noop())
        assert not is_stubbed()
        reset_validator()
        assert is_stubbed()
