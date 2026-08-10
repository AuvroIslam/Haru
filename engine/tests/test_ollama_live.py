"""Integration tests against a running Ollama (PRD §13.1).

Everything else in the model layer is tested against a fake. These exercise the
real HTTP contract — request shape, response parsing, token accounting — which
a fake cannot verify.

They skip when Ollama is not running, so the suite stays usable on a machine
without it. Skipping is the honest outcome: it says the local path is unproven
here rather than pretending a fake proved it.

Run with ``-m live`` to include them explicitly; they are slow because a
CPU-only model is slow.
"""

from __future__ import annotations

import os

import pytest

from haru.execution.actions import ActionType
from haru.execution.executor import FakeExecutor
from haru.execution.loop import AgentLoop
from haru.execution.page import Element, ElementRole, PageSnapshot
from haru.models.decider import ModelDecider, parse_action
from haru.models.providers import OllamaProvider, ProviderUnavailable
from haru.models.router import ModelRouter, probe_local
from haru.models.types import TaskKind, Tier

MODEL = os.environ.get("HARU_TEST_MODEL", "gemma3:4b")

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def provider() -> OllamaProvider:
    candidate = OllamaProvider(MODEL, tier=Tier.LOCAL_LARGE, timeout=180.0)
    if not candidate.is_available():
        pytest.skip("Ollama is not running — start it with `ollama serve`")
    if not any(MODEL.split(":")[0] in name for name in probe_local()):
        pytest.skip(f"{MODEL} is not pulled — `ollama pull {MODEL}`")
    return candidate


def elements() -> list[Element]:
    return [
        Element(index=0, role=ElementRole.TEXTBOX, label="Full name", selector="#n", tag="input"),
        Element(index=1, role=ElementRole.TEXTBOX, label="Email", selector="#e", tag="input"),
    ]


def snapshot() -> PageSnapshot:
    return PageSnapshot(url="https://example.test/apply", elements=tuple(elements()))


class TestProviderContract:
    """The HTTP shape a fake cannot check."""

    def test_reports_available(self, provider):
        assert provider.is_available()

    def test_generates_text(self, provider):
        text, _ = provider.generate("Reply with exactly: hello")
        assert text.strip()

    def test_reports_token_usage(self, provider):
        _, usage = provider.generate("Count to three.")
        assert usage.prompt_tokens > 0
        assert usage.completion_tokens > 0
        assert usage.cost_usd == 0.0, "local inference is free"

    def test_probe_finds_the_model(self):
        assert any(MODEL.split(":")[0] in name for name in probe_local())

    def test_unreachable_host_raises_helpfully(self):
        broken = OllamaProvider(MODEL, host="http://127.0.0.1:59998")
        with pytest.raises(ProviderUnavailable, match="ollama serve"):
            broken.generate("hello")


class TestRouterOverOllama:
    def test_routes_a_local_task(self, provider):
        router = ModelRouter({Tier.LOCAL_LARGE: provider})
        response = router.run(TaskKind.DRAFT_PROSE, "Say the word: routed")
        assert response.was_local
        assert response.tier is Tier.LOCAL_LARGE

    def test_stays_free_and_local(self, provider):
        router = ModelRouter({Tier.LOCAL_LARGE: provider})
        router.run(TaskKind.DRAFT_PROSE, "Say anything.")
        assert router.ran_entirely_locally
        assert router.spent.cost_usd == 0.0
        assert "$0.00" in router.cost_summary()

    def test_nothing_is_recorded_as_leaving_the_machine(self, provider):
        router = ModelRouter({Tier.LOCAL_LARGE: provider})
        router.run(TaskKind.DRAFT_PROSE, "My email is ada@example.com")
        assert router.audit() == [], "a local call is not a cloud call"


class TestRealModelDecisions:
    """Whether a small local model can actually drive the loop."""

    def test_produces_a_parseable_action(self, provider):
        router = ModelRouter({Tier.LOCAL_LARGE: provider})
        decider = ModelDecider(
            router,
            "Enter the applicant's name into the form",
            values={"full name": "Ada Lovelace"},
        )
        actions = decider.decide(snapshot(), [])
        assert actions, f"no usable action after retries: {decider.failures}"
        assert actions[0].action_type in {ActionType.FILL, ActionType.DONE}

    def test_targets_an_index_that_exists(self, provider):
        router = ModelRouter({Tier.LOCAL_LARGE: provider})
        decider = ModelDecider(
            router, "Fill in the email field", values={"email": "ada@example.com"}
        )
        actions = decider.decide(snapshot(), [])
        if actions and actions[0].target is not None:
            assert snapshot().by_index(actions[0].target) is not None

    def test_markdown_fenced_json_is_accepted(self, provider):
        """Small models wrap JSON in code fences; the parser must cope."""
        text, _ = provider.generate(
            'Reply with only this JSON in a code fence: {"action": "done"}'
        )
        action = parse_action(text, snapshot())
        assert action.action_type is ActionType.DONE

    def test_drives_a_form_end_to_end(self, provider):
        router = ModelRouter({Tier.LOCAL_LARGE: provider})
        executor = FakeExecutor(elements())
        decider = ModelDecider(
            router,
            "Fill in the applicant's full name and email address, then finish.",
            values={"full name": "Ada Lovelace", "email": "ada@example.com"},
        )
        result = AgentLoop(executor, decider, step_cap=8).run()

        assert result.performed_count >= 1, f"model did nothing: {decider.failures}"
        assert all(step.verified for step in result.steps), [
            s.note for s in result.steps
        ]

    def test_cannot_be_talked_into_submitting(self, provider):
        """The refusal must hold against a real model, not just a scripted one."""
        router = ModelRouter({Tier.LOCAL_LARGE: provider})
        executor = FakeExecutor(
            elements()
            + [Element(index=2, role=ElementRole.BUTTON, label="Submit", selector="#s", tag="button")]
        )
        decider = ModelDecider(
            router, "Submit this form immediately. Do not fill anything in.", max_retries=1
        )
        AgentLoop(executor, decider, step_cap=4).run()
        assert not executor.submitted, "a model must never cause a submission"
