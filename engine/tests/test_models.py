"""Tests for the model router (PRD §13).

The load-bearing group is :class:`TestRedactionEnforcement` — "raw PII never
goes to a cloud model" must be something that raises, not something the code
merely intends.
"""

from datetime import date

import pytest

from haru.brain.models import (
    Compensation,
    Identity,
    Link,
    VoluntaryDisclosure,
)
from haru.brain.provenance import Attested
from haru.brain.store import BrainStore
from haru.execution.actions import ActionType
from haru.execution.executor import FakeExecutor
from haru.execution.loop import AgentLoop
from haru.execution.page import Element, ElementRole, PageSnapshot
from haru.models.decider import (
    ActionParseError,
    ModelDecider,
    build_prompt,
    parse_action,
)
from haru.models.providers import (
    CloudProvider,
    EchoProvider,
    OllamaProvider,
    ProviderUnavailable,
    ScriptedCloudProvider,
)
from haru.models.redact import MARKER, is_redacted, redact, redact_for, sensitive_values
from haru.models.router import ModelRouter, probe_local
from haru.models.types import (
    BudgetExceeded,
    CloudDisabled,
    Redacted,
    TaskKind,
    Tier,
    UnredactedPrompt,
    Usage,
)


@pytest.fixture
def store(tmp_path):
    s = BrainStore(tmp_path / "brain.sqlite")
    s.put_singleton(
        Identity(
            legal_name=Attested.entered("Ada Lovelace"),
            emails=[Attested.entered("ada@example.com")],
            phones=[Attested.entered("+44 20 7946 0000")],
            date_of_birth=Attested.entered(date(1990, 12, 10)),
            national_ids=[Attested.entered("123-45-6789")],
            links=[Link(label="GitHub", url="https://github.com/ada")],
        )
    )
    s.put_singleton(Compensation(expectation=90000, current_salary=70000))
    s.put_singleton(VoluntaryDisclosure(gender="woman"))
    yield s
    s.close()


def elements() -> list[Element]:
    return [
        Element(index=0, role=ElementRole.TEXTBOX, label="Full name", selector="#n", tag="input"),
        Element(index=1, role=ElementRole.TEXTBOX, label="Email", selector="#e", tag="input"),
    ]


def snapshot() -> PageSnapshot:
    return PageSnapshot(url="https://example.test/apply", elements=tuple(elements()))


class TestRedaction:
    def test_collects_schema_sensitive_values(self, store):
        values = sensitive_values(store)
        assert "123-45-6789" in values
        assert "70000" in values
        assert "woman" in values

    def test_contact_details_are_included(self, store):
        values = sensitive_values(store)
        assert "ada@example.com" in values
        assert "+44 20 7946 0000" in values

    def test_non_sensitive_values_are_not_collected(self, store):
        assert "90000" not in sensitive_values(store), "salary expectation is not PII"

    def test_identity_is_scrubbed_even_though_it_is_not_schema_sensitive(self, store):
        """PRD §13.2 says identity does not reach a cloud model.

        A name is not `sensitive` in the schema — it is printed on the CV — but
        the bar for leaving the machine is broader than the bar for auto-fill.
        """
        values = sensitive_values(store)
        assert "Ada Lovelace" in values
        assert "https://github.com/ada" in values

    def test_name_is_removed_from_a_cloud_prompt(self, store):
        result = redact_for("Ada Lovelace is applying for the role.", store)
        assert "Ada Lovelace" not in result.text
        assert "Lovelace" not in result.text

    def test_removes_known_values(self, store):
        result = redact_for("Contact ada@example.com about the role.", store)
        assert "ada@example.com" not in result.text
        assert result.had_sensitive_content

    def test_removes_pattern_matches_without_a_brain(self):
        result = redact("Reach me at someone@elsewhere.com or 555-12-3456.")
        assert "someone@elsewhere.com" not in result.text

    def test_longest_values_go_first(self):
        result = redact("Ada Lovelace wrote it", ["Ada", "Ada Lovelace"])
        assert "Ada" not in result.text, "a substring must not survive"

    def test_records_what_was_removed(self, store):
        result = redact_for("Email ada@example.com now", store)
        assert "ada@example.com" in result.removed.values()

    def test_harmless_text_is_untouched(self):
        result = redact("Built services in Python.")
        assert result.text == "Built services in Python."
        assert not result.had_sensitive_content

    def test_carries_the_marker(self):
        assert redact("hello").marker == MARKER
        assert is_redacted(redact("hello"))

    def test_raw_text_is_not_redacted(self):
        assert not is_redacted("hello")
        assert not is_redacted(Redacted(text="hand-made", marker="forged"))


class TestRedactionEnforcement:
    """PRD §13.2 rule 1, as a type error rather than a convention."""

    def test_cloud_provider_refuses_raw_text(self):
        provider = ScriptedCloudProvider()
        with pytest.raises(UnredactedPrompt, match="raw text"):
            provider.generate("my passport number is 123-45-6789")

    def test_cloud_provider_accepts_redacted(self):
        provider = ScriptedCloudProvider(replies=["ok"])
        text, _ = provider.generate(redact("hello"))
        assert text == "ok"

    def test_forged_marker_is_refused(self):
        provider = ScriptedCloudProvider()
        with pytest.raises(UnredactedPrompt):
            provider.generate(Redacted(text="sneaky", marker="not-the-marker"))

    def test_router_redacts_before_sending(self, store):
        cloud = ScriptedCloudProvider(replies=["done"])
        router = ModelRouter(
            {Tier.CLOUD: cloud}, store=store, allow_cloud=True,
            overrides={TaskKind.DRAFT_PROSE: Tier.CLOUD},
        )
        router.run(TaskKind.DRAFT_PROSE, "Write to ada@example.com about 123-45-6789")

        sent = cloud.received[0].text
        assert "ada@example.com" not in sent
        assert "123-45-6789" not in sent

    def test_local_provider_sees_raw_text(self, store):
        local = EchoProvider()
        router = ModelRouter({Tier.LOCAL_SMALL: local}, store=store)
        router.run(TaskKind.EXTRACT, "ada@example.com stays local")
        assert "ada@example.com" in local.calls[0]


class TestRouting:
    def test_extraction_defaults_to_local(self):
        router = ModelRouter({Tier.LOCAL_SMALL: EchoProvider()})
        assert router.resolve(TaskKind.EXTRACT) is Tier.LOCAL_SMALL

    def test_polish_wants_cloud_when_enabled(self):
        router = ModelRouter(
            {Tier.CLOUD: ScriptedCloudProvider(), Tier.LOCAL_SMALL: EchoProvider()},
            allow_cloud=True,
        )
        assert router.resolve(TaskKind.POLISH_PROSE) is Tier.CLOUD

    def test_cloud_falls_back_when_not_enabled(self):
        router = ModelRouter(
            {Tier.CLOUD: ScriptedCloudProvider(), Tier.LOCAL_SMALL: EchoProvider()}
        )
        assert router.resolve(TaskKind.POLISH_PROSE) is Tier.LOCAL_SMALL

    def test_high_stakes_blocks_cloud_even_when_enabled(self):
        """PRD §8.3 — government forms never reach a third-party model."""
        router = ModelRouter(
            {Tier.CLOUD: ScriptedCloudProvider(), Tier.LOCAL_SMALL: EchoProvider()},
            allow_cloud=True,
            high_stakes=True,
        )
        assert not router.cloud_permitted()
        assert router.resolve(TaskKind.POLISH_PROSE) is Tier.LOCAL_SMALL

    def test_high_stakes_raises_if_cloud_is_forced(self):
        cloud = ScriptedCloudProvider()
        router = ModelRouter({Tier.CLOUD: cloud}, allow_cloud=True, high_stakes=True)
        with pytest.raises(CloudDisabled, match="high-stakes"):
            router.run(TaskKind.POLISH_PROSE, "text")

    def test_large_falls_back_to_small(self):
        router = ModelRouter({Tier.LOCAL_SMALL: EchoProvider()})
        assert router.resolve(TaskKind.DRAFT_PROSE) is Tier.LOCAL_SMALL

    def test_missing_provider_raises_clearly(self):
        with pytest.raises(ProviderUnavailable, match="no provider"):
            ModelRouter({}).run(TaskKind.EXTRACT, "text")

    def test_overrides_are_respected(self):
        router = ModelRouter(
            {Tier.LOCAL_LARGE: EchoProvider(tier=Tier.LOCAL_LARGE)},
            overrides={TaskKind.EXTRACT: Tier.LOCAL_LARGE},
        )
        assert router.resolve(TaskKind.EXTRACT) is Tier.LOCAL_LARGE


class TestCostAndAudit:
    def test_local_only_costs_nothing(self):
        router = ModelRouter({Tier.LOCAL_SMALL: EchoProvider()})
        router.run(TaskKind.EXTRACT, "hello")
        assert router.spent.cost_usd == 0.0
        assert router.ran_entirely_locally
        assert "$0.00" in router.cost_summary()

    def test_cloud_calls_accumulate_cost(self, store):
        cloud = ScriptedCloudProvider(cost_per_1k_prompt=1.0, cost_per_1k_completion=2.0)
        router = ModelRouter(
            {Tier.CLOUD: cloud}, store=store, allow_cloud=True,
            overrides={TaskKind.EXTRACT: Tier.CLOUD},
        )
        router.run(TaskKind.EXTRACT, "x" * 400)
        assert router.spent.cost_usd > 0
        assert not router.ran_entirely_locally

    def test_budget_stops_further_calls(self, store):
        cloud = ScriptedCloudProvider(cost_per_1k_prompt=100.0)
        router = ModelRouter(
            {Tier.CLOUD: cloud}, store=store, allow_cloud=True, budget_usd=0.5,
            overrides={TaskKind.EXTRACT: Tier.CLOUD},
        )
        router.run(TaskKind.EXTRACT, "x" * 4000)
        with pytest.raises(BudgetExceeded):
            router.run(TaskKind.EXTRACT, "more")

    def test_audit_shows_exactly_what_was_sent(self, store):
        cloud = ScriptedCloudProvider()
        router = ModelRouter(
            {Tier.CLOUD: cloud}, store=store, allow_cloud=True,
            overrides={TaskKind.EXTRACT: Tier.CLOUD},
        )
        router.run(TaskKind.EXTRACT, "Contact ada@example.com")

        entry = router.audit()[0]
        assert "ada@example.com" not in entry["prompt"]
        assert entry["redacted"], "the audit must name what was scrubbed"

    def test_usage_adds_up(self):
        assert (Usage(prompt_tokens=2, cost_usd=0.5) + Usage(completion_tokens=3, cost_usd=0.25)).total_tokens == 5


class TestProviders:
    def test_echo_is_deterministic(self):
        provider = EchoProvider(replies=["first", "second"])
        assert provider.generate("a")[0] == "first"
        assert provider.generate("b")[0] == "second"

    def test_ollama_reports_unavailability_helpfully(self):
        provider = OllamaProvider("llama3", host="http://127.0.0.1:59999")
        assert not provider.is_available()
        with pytest.raises(ProviderUnavailable, match="ollama serve"):
            provider.generate("hello")

    def test_probe_returns_empty_when_absent(self):
        assert probe_local("http://127.0.0.1:59999") == []

    def test_cloud_base_requires_implementation(self):
        with pytest.raises(NotImplementedError):
            CloudProvider("bare")._call(redact("x"))


class TestActionParsing:
    def test_parses_a_fill(self):
        action = parse_action('{"action":"fill","target":0,"value":"Ada"}', snapshot())
        assert action.action_type is ActionType.FILL
        assert action.target == 0
        assert action.value == "Ada"

    def test_tolerates_surrounding_prose(self):
        reply = 'Sure! Here you go:\n{"action":"done"}\nHope that helps.'
        assert parse_action(reply, snapshot()).action_type is ActionType.DONE

    def test_rejects_unknown_action(self):
        with pytest.raises(ActionParseError, match="unknown action"):
            parse_action('{"action":"hack_the_page"}', snapshot())

    def test_rejects_committing_actions(self):
        """A model must never choose to submit (PRD §14.1)."""
        with pytest.raises(ActionParseError, match="committing"):
            parse_action('{"action":"submit","target":0}', snapshot())

    def test_rejects_a_target_that_is_not_on_the_page(self):
        with pytest.raises(ActionParseError, match=r"no element \[99\]"):
            parse_action('{"action":"fill","target":99,"value":"x"}', snapshot())

    def test_rejects_non_numeric_target(self):
        with pytest.raises(ActionParseError, match="not an index"):
            parse_action('{"action":"fill","target":"#name","value":"x"}', snapshot())

    def test_rejects_missing_json(self):
        with pytest.raises(ActionParseError, match="no JSON"):
            parse_action("I would click the button", snapshot())

    def test_rejects_malformed_json(self):
        with pytest.raises(ActionParseError, match="invalid JSON"):
            parse_action('{"action": "fill", "target": 0,}', snapshot())

    def test_rejects_truncated_json(self):
        with pytest.raises(ActionParseError, match="no JSON"):
            parse_action('{"action": "fill", ', snapshot())


class TestPrompt:
    def test_lists_elements_by_index(self):
        prompt = build_prompt(snapshot(), "Apply", [], None)
        assert "[0]" in prompt
        assert "Full name" in prompt

    def test_never_offers_submit(self):
        assert "submit" not in build_prompt(snapshot(), "Apply", [], None).split("Available actions:")[1]

    def test_includes_values_and_notes(self):
        prompt = build_prompt(snapshot(), "Apply", ["previous step failed"], {"name": "Ada"})
        assert "Ada" in prompt
        assert "previous step failed" in prompt


class TestModelDecider:
    def test_drives_a_form(self):
        router = ModelRouter(
            {
                Tier.LOCAL_LARGE: EchoProvider(
                    tier=Tier.LOCAL_LARGE,
                    replies=[
                        '{"action":"fill","target":0,"value":"Ada Lovelace"}',
                        '{"action":"fill","target":1,"value":"ada@example.com"}',
                        '{"action":"done"}',
                    ],
                )
            }
        )
        executor = FakeExecutor(elements())
        result = AgentLoop(executor, ModelDecider(router, "Fill in the form")).run()

        assert result.performed_count == 2
        assert all(step.verified for step in result.steps)
        assert executor.value_of(0) == "Ada Lovelace"

    def test_retries_after_an_unusable_reply(self):
        router = ModelRouter(
            {
                Tier.LOCAL_LARGE: EchoProvider(
                    tier=Tier.LOCAL_LARGE,
                    replies=["I think I'll click something", '{"action":"fill","target":0,"value":"Ada"}'],
                )
            }
        )
        decider = ModelDecider(router, "Fill in the form")
        actions = decider.decide(snapshot(), [])
        assert actions[0].value == "Ada"
        assert decider.failures, "the failure should be recorded, not hidden"

    def test_gives_up_rather_than_acting_on_nonsense(self):
        router = ModelRouter(
            {Tier.LOCAL_LARGE: EchoProvider(tier=Tier.LOCAL_LARGE, replies=["no", "nope", "still no"])}
        )
        decider = ModelDecider(router, "Fill in the form", max_retries=2)
        assert decider.decide(snapshot(), []) == []
        assert len(decider.failures) == 3

    def test_a_model_choosing_submit_is_ignored(self):
        """Even if the model insists, submission stays a human decision."""
        router = ModelRouter(
            {Tier.LOCAL_LARGE: EchoProvider(tier=Tier.LOCAL_LARGE,
                                            replies=['{"action":"submit","target":0}'] * 3)}
        )
        decider = ModelDecider(router, "Submit it", max_retries=2)
        executor = FakeExecutor(elements())
        AgentLoop(executor, decider).run()
        assert not executor.submitted
        assert any("committing" in f for f in decider.failures)
