"""Tests for the execution core (PRD §12).

The load-bearing behaviours: one action per turn, post-action verification,
approval gates that cannot be skipped, and the interlock that prevents any
submission while validation is stubbed.
"""

import pytest

from haru.execution.actions import (
    ACTION_SPECS,
    Action,
    ActionClass,
    ActionType,
    Verification,
    committing_types,
)
from haru.execution.executor import FakeExecutor
from haru.execution.guard import KillSwitch, LoopGuard, StepBudget, StopReason
from haru.execution.loop import AgentLoop, ScriptedDecider, verify
from haru.execution.page import Element, ElementRole, PageSnapshot
from haru.validation.seam import reset_validator, set_validator
from haru.validation.types import Result, ValidationMode


class RealValidator:
    """Stand-in for M3 — enough to lift the stubbed-submission interlock."""

    def validate(self, artifact, boundary, mode=ValidationMode.NORMAL):
        return Result(artifact=artifact, mode=mode)


@pytest.fixture(autouse=True)
def _clean_validator():
    reset_validator()
    yield
    reset_validator()


def form_elements() -> list[Element]:
    return [
        Element(index=0, role=ElementRole.TEXTBOX, label="Full name", selector="#name", tag="input", required=True),
        Element(index=1, role=ElementRole.TEXTBOX, label="Email", selector="#email", tag="input", required=True),
        Element(index=2, role=ElementRole.SELECT, label="Country", selector="#country", tag="select", options=("UK", "US")),
        Element(index=3, role=ElementRole.CHECKBOX, label="Agree", selector="#agree", tag="input"),
        Element(index=4, role=ElementRole.FILE, label="Resume", selector="#cv", tag="input"),
        Element(index=5, role=ElementRole.BUTTON, label="Submit", selector="#submit", tag="button"),
    ]


@pytest.fixture
def executor():
    return FakeExecutor(form_elements())


def fill(target: int, value: str) -> Action:
    return Action(action_type=ActionType.FILL, target=target, value=value)


class TestActionRegistry:
    def test_every_action_type_has_a_spec(self):
        for action_type in ActionType:
            assert action_type in ACTION_SPECS

    def test_submit_is_committing(self):
        assert ACTION_SPECS[ActionType.SUBMIT].action_class is ActionClass.COMMITTING
        assert committing_types() == {ActionType.SUBMIT}

    def test_upload_is_sensitive(self):
        assert ACTION_SPECS[ActionType.UPLOAD].action_class is ActionClass.SENSITIVE

    def test_committing_and_sensitive_need_approval(self):
        assert Action(action_type=ActionType.SUBMIT, target=5).needs_approval
        assert Action(action_type=ActionType.UPLOAD, target=4, value="cv.pdf").needs_approval

    def test_ordinary_actions_do_not(self):
        assert not fill(0, "Ada").needs_approval
        assert not Action(action_type=ActionType.CLICK, target=5).needs_approval

    def test_target_is_required_where_declared(self):
        with pytest.raises(ValueError, match="requires a target"):
            Action(action_type=ActionType.CLICK)

    def test_navigate_requires_a_url(self):
        with pytest.raises(ValueError, match="url"):
            Action(action_type=ActionType.NAVIGATE)

    def test_irreversible_actions_are_marked(self):
        assert not ACTION_SPECS[ActionType.SUBMIT].reversible
        assert ACTION_SPECS[ActionType.FILL].reversible

    def test_signature_uses_stable_key_not_index(self):
        action = fill(0, "Ada")
        assert action.signature("abc123") == action.signature("abc123")
        assert action.signature("abc123") != action.signature("def456")


class TestElements:
    def test_stable_key_survives_renumbering(self):
        a = Element(index=0, role=ElementRole.TEXTBOX, label="Email", selector="#e", tag="input")
        renumbered = a.model_copy(update={"index": 7})
        assert a.stable_key == renumbered.stable_key

    def test_stable_key_distinguishes_elements(self):
        a = Element(index=0, role=ElementRole.TEXTBOX, label="Email", selector="#e", tag="input")
        b = Element(index=1, role=ElementRole.TEXTBOX, label="Phone", selector="#p", tag="input")
        assert a.stable_key != b.stable_key

    def test_zero_size_elements_are_still_representable(self):
        # Invisible click overlays are real targets.
        el = Element(index=0, role=ElementRole.BUTTON, label="Go", tag="button")
        assert el.width == 0.0 and el.height == 0.0

    def test_unfilled_required_fields(self, executor):
        snap = executor.snapshot()
        assert {e.label for e in snap.unfilled_required} == {"Full name", "Email"}

    def test_digest_changes_with_values(self, executor):
        before = executor.snapshot().digest()
        executor.perform(fill(0, "Ada"), executor.snapshot().by_index(0))
        assert executor.snapshot().digest() != before

    def test_lookup_helpers(self, executor):
        snap = executor.snapshot()
        assert snap.by_index(0).label == "Full name"
        assert snap.by_label("Email").index == 1
        assert snap.by_index(99) is None


class TestVerification:
    """PRD §12.3 — an unverified action is a failed action."""

    def test_value_readback_passes_when_it_sticks(self, executor):
        before = executor.snapshot()
        action = fill(0, "Ada")
        executor.perform(action, before.by_index(0))
        ok, _ = verify(action, before, executor.snapshot())
        assert ok

    def test_value_readback_catches_silent_discard(self):
        """The React-controlled-input bug, caught rather than believed."""
        ex = FakeExecutor(form_elements(), framework_controlled={"Full name"})
        before = ex.snapshot()
        action = fill(0, "Ada")
        ex.perform(action, before.by_index(0))

        ok, why = verify(action, before, ex.snapshot())
        assert not ok
        assert "framework-controlled" in why

    def test_url_change_verifies_navigation(self, executor):
        before = executor.snapshot()
        action = Action(action_type=ActionType.NAVIGATE, url="https://example.test/next")
        executor.perform(action, None)
        ok, _ = verify(action, before, executor.snapshot())
        assert ok

    def test_navigation_that_did_not_move_fails(self, executor):
        before = executor.snapshot()
        action = Action(action_type=ActionType.NAVIGATE, url=before.url)
        executor.perform(action, None)
        ok, why = verify(action, before, executor.snapshot())
        assert not ok
        assert "url did not change" in why

    def test_click_requires_the_page_to_change(self, executor):
        before = executor.snapshot()
        action = Action(action_type=ActionType.CLICK, target=5)
        executor.perform(action, before.by_index(5))
        ok, why = verify(action, before, executor.snapshot())
        assert not ok, "a click that changed nothing must not report success"
        assert "page did not change" in why

    def test_checkbox_toggle_verifies(self, executor):
        before = executor.snapshot()
        action = Action(action_type=ActionType.CHECK, target=3, value="true")
        executor.perform(action, before.by_index(3))
        ok, _ = verify(action, before, executor.snapshot())
        assert ok

    def test_upload_needs_the_filename_visible(self, executor):
        before = executor.snapshot()
        action = Action(action_type=ActionType.UPLOAD, target=4, value="cv.pdf")
        executor.perform(action, before.by_index(4))
        ok, _ = verify(action, before, executor.snapshot())
        assert ok

    def test_submit_needs_a_confirmation(self, executor):
        before = executor.snapshot()
        action = Action(action_type=ActionType.SUBMIT, target=5)
        executor.perform(action, before.by_index(5))
        ok, _ = verify(action, before, executor.snapshot())
        assert ok

    def test_submit_without_confirmation_fails(self):
        ex = FakeExecutor(form_elements(), submit_confirms=False)
        before = ex.snapshot()
        action = Action(action_type=ActionType.SUBMIT, target=5)
        ex.perform(action, before.by_index(5))
        ok, why = verify(action, before, ex.snapshot())
        assert not ok
        assert "no confirmation" in why

    def test_free_actions_need_no_verification(self, executor):
        before = executor.snapshot()
        action = Action(action_type=ActionType.SCREENSHOT)
        ok, _ = verify(action, before, before)
        assert ok


class TestOneActionPerTurn:
    """PRD §12.2 — however many are offered, exactly one runs."""

    def test_only_the_first_action_of_a_batch_runs(self, executor):
        class Greedy:
            def __init__(self):
                self.calls = 0

            def decide(self, snapshot, notes):
                self.calls += 1
                if self.calls > 1:
                    return []
                return [fill(0, "Ada"), fill(1, "ada@example.com"), fill(2, "UK")]

        AgentLoop(executor, Greedy()).run()
        assert len(executor.performed) == 1
        assert executor.value_of(0) == "Ada"
        assert executor.value_of(1) is None

    def test_loop_rescans_between_actions(self, executor):
        seen_digests = []

        class Watcher:
            def __init__(self):
                self.queue = [fill(0, "Ada"), fill(1, "ada@example.com")]

            def decide(self, snapshot, notes):
                seen_digests.append(snapshot.digest())
                return [self.queue.pop(0)] if self.queue else []

        AgentLoop(executor, Watcher()).run()
        assert len(set(seen_digests)) == len(seen_digests), "each turn sees a fresh page"


class TestApprovalGates:
    """PRD §14.1 — committing and sensitive actions never run unattended."""

    def test_submit_blocked_without_an_approver(self, executor):
        set_validator(RealValidator())
        loop = AgentLoop(executor, ScriptedDecider([Action(action_type=ActionType.SUBMIT, target=5)]))
        result = loop.run()
        assert result.reason is StopReason.AWAITING_APPROVAL
        assert not executor.submitted

    def test_submit_blocked_when_approver_declines(self, executor):
        set_validator(RealValidator())
        loop = AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.SUBMIT, target=5)]),
            approval=lambda a, s: False,
        )
        assert loop.run().reason is StopReason.AWAITING_APPROVAL
        assert not executor.submitted

    def test_submit_proceeds_when_approved(self, executor):
        set_validator(RealValidator())
        loop = AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.SUBMIT, target=5)]),
            approval=lambda a, s: True,
        )
        result = loop.run()
        assert executor.submitted
        assert result.steps[-1].verified

    def test_upload_also_requires_approval(self, executor):
        loop = AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.UPLOAD, target=4, value="cv.pdf")]),
        )
        assert loop.run().reason is StopReason.AWAITING_APPROVAL

    def test_ordinary_actions_need_no_approver(self, executor):
        loop = AgentLoop(executor, ScriptedDecider([fill(0, "Ada")]))
        assert loop.run().reason is StopReason.COMPLETED
        assert executor.value_of(0) == "Ada"

    def test_approver_sees_the_action_and_page(self, executor):
        set_validator(RealValidator())
        seen = {}

        def approve(action, snapshot):
            seen["action"] = action
            seen["url"] = snapshot.url
            return True

        AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.SUBMIT, target=5)]),
            approval=approve,
        ).run()
        assert seen["action"].action_type is ActionType.SUBMIT
        assert "example.test" in seen["url"]


class TestStubbedValidationInterlock:
    """PRD §17.1 — M3 ships before M4, enforced rather than remembered."""

    def test_submit_refused_while_validation_is_stubbed(self, executor):
        loop = AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.SUBMIT, target=5)]),
            approval=lambda a, s: True,
        )
        result = loop.run()
        assert result.reason is StopReason.BLOCKED
        assert not executor.submitted
        assert any("stubbed" in n for n in result.notes)

    def test_non_committing_actions_still_run_while_stubbed(self, executor):
        loop = AgentLoop(executor, ScriptedDecider([fill(0, "Ada")]))
        assert loop.run().reason is StopReason.COMPLETED

    def test_interlock_lifts_with_a_real_validator(self, executor):
        set_validator(RealValidator())
        loop = AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.SUBMIT, target=5)]),
            approval=lambda a, s: True,
        )
        assert loop.run().reason is StopReason.COMPLETED
        assert executor.submitted

    def test_escape_hatch_is_explicit(self, executor):
        loop = AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.SUBMIT, target=5)]),
            approval=lambda a, s: True,
            allow_submit_while_stubbed=True,
        )
        assert loop.run().reason is StopReason.COMPLETED


class TestGuards:
    def test_loop_guard_nudges_before_giving_up(self, executor):
        class Stubborn:
            def decide(self, snapshot, notes):
                return [Action(action_type=ActionType.CLICK, target=5)]

        result = AgentLoop(executor, Stubborn(), step_cap=20).run()
        assert result.reason is StopReason.REPEATED
        assert any("already been performed" in n for n in result.notes)

    def test_repeat_does_not_re_run_the_action(self, executor):
        class Stubborn:
            def decide(self, snapshot, notes):
                return [Action(action_type=ActionType.CLICK, target=5)]

        AgentLoop(executor, Stubborn(), step_cap=20).run()
        clicks = [a for a in executor.performed if a.action_type is ActionType.CLICK]
        assert len(clicks) < 3, "a repeat must nudge, not fire again"

    def test_step_cap_stops_varied_but_useless_work(self, executor):
        class Wanderer:
            def __init__(self):
                self.n = 0

            def decide(self, snapshot, notes):
                self.n += 1
                return [fill(0, f"value-{self.n}")]

        result = AgentLoop(executor, Wanderer(), step_cap=5).run()
        assert result.reason is StopReason.STEP_CAP
        assert result.performed_count == 5

    def test_kill_switch_halts_immediately(self, executor):
        switch = KillSwitch()

        class Endless:
            def __init__(self):
                self.n = 0

            def decide(self, snapshot, notes):
                self.n += 1
                if self.n == 2:
                    switch.stop()
                return [fill(0, f"v{self.n}")]

        result = AgentLoop(executor, Endless(), kill_switch=switch, step_cap=50).run()
        assert result.reason is StopReason.KILLED
        assert result.performed_count == 1

    def test_guard_counts_and_limits(self):
        guard = LoopGuard(repeat_limit=2)
        assert guard.record("a") == 1
        assert not guard.should_stop("a")
        assert guard.record("a") == 2
        assert guard.should_stop("a")

    def test_budget(self):
        budget = StepBudget(cap=2)
        budget.spend()
        assert budget.remaining == 1
        budget.spend()
        assert budget.exhausted


class TestFailures:
    def test_disabled_element_fails_the_step(self, executor):
        executor.set_disabled(0)
        result = AgentLoop(executor, ScriptedDecider([fill(0, "Ada")])).run()
        assert result.reason is StopReason.FAILED
        assert "disabled" in result.steps[-1].note

    def test_missing_target_fails_cleanly(self, executor):
        result = AgentLoop(executor, ScriptedDecider([fill(99, "Ada")])).run()
        assert result.reason is StopReason.FAILED

    def test_invalid_option_fails(self, executor):
        result = AgentLoop(
            executor,
            ScriptedDecider([Action(action_type=ActionType.SELECT, target=2, value="Mars")]),
        ).run()
        assert result.reason is StopReason.FAILED

    def test_unverified_action_is_reported_not_hidden(self):
        ex = FakeExecutor(form_elements(), framework_controlled={"Full name"})
        result = AgentLoop(ex, ScriptedDecider([fill(0, "Ada")])).run()
        step = result.steps[0]
        assert step.performed
        assert not step.verified
        assert "unverified" in step.note


class TestFullRun:
    def test_fills_a_form_and_submits_with_approval(self, executor):
        set_validator(RealValidator())
        result = AgentLoop(
            executor,
            ScriptedDecider(
                [
                    fill(0, "Ada Lovelace"),
                    fill(1, "ada@example.com"),
                    Action(action_type=ActionType.SELECT, target=2, value="UK"),
                    Action(action_type=ActionType.CHECK, target=3, value="true"),
                    Action(action_type=ActionType.SUBMIT, target=5),
                ]
            ),
            approval=lambda a, s: True,
        ).run()

        assert result.reason is StopReason.COMPLETED
        assert result.performed_count == 5
        assert all(s.verified for s in result.steps)
        assert executor.submitted
        assert executor.value_of(0) == "Ada Lovelace"
        assert executor.value_of(2) == "UK"

    def test_done_action_finishes(self, executor):
        result = AgentLoop(
            executor, ScriptedDecider([fill(0, "Ada"), Action(action_type=ActionType.DONE)])
        ).run()
        assert result.reason is StopReason.COMPLETED
        assert result.performed_count == 1
