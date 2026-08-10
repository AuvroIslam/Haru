"""The agent loop (PRD §12.2, §12.3).

    scan → decide → take EXACTLY ONE action → verify it landed → rescan → repeat

**One action per turn, always** — even when the decider returns several, only
the first runs. Multi-step plans go stale the instant the page changes, and the
resulting bug (an action fired against a page that no longer exists) is both
common and invisible. NaviNate arrived at the same rule the hard way; their code
calls it "the real fix for the 'did it 4 times' bug".

**An unverified action is a failed action.** After every step the loop confirms
the observable result before believing it happened. Reporting success without
checking is the gap NaviNate shipped with and named their top regret, so it is
a principle here rather than a later refinement (P4).

Two safety interlocks live in this file because they must not be optional:

* committing and sensitive actions require explicit approval (PRD §14.1);
* nothing may be submitted while validation is stubbed, which is what enforces
  "M3 ships before M4" structurally rather than by memory (PRD §17.1).
"""

from __future__ import annotations

import logging
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from haru.execution.actions import Action, ActionClass, ActionType, Verification
from haru.execution.executor import ExecutionError, Executor, TargetNotFound
from haru.execution.guard import (
    DEFAULT_STEP_CAP,
    KillSwitch,
    LoopGuard,
    StepBudget,
    StopReason,
)
from haru.execution.page import PageSnapshot
from haru.validation.seam import is_stubbed

log = logging.getLogger(__name__)


class Decider(Protocol):
    """Chooses the next action. A model in production, a script in tests."""

    def decide(self, snapshot: PageSnapshot, notes: list[str]) -> list[Action]:
        ...


#: Returns True to allow a committing or sensitive action.
ApprovalHook = Callable[[Action, PageSnapshot], bool]


class Step(BaseModel):
    """One completed turn of the loop."""

    model_config = ConfigDict(frozen=True)

    action: Action
    performed: bool
    verified: bool
    note: str = ""
    digest_before: str = ""
    digest_after: str = ""


class RunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: StopReason
    steps: tuple[Step, ...] = ()
    notes: tuple[str, ...] = ()
    pending_action: Action | None = None

    @property
    def succeeded(self) -> bool:
        return self.reason is StopReason.COMPLETED

    @property
    def performed_count(self) -> int:
        return sum(1 for s in self.steps if s.performed)


def verify(
    action: Action, before: PageSnapshot, after: PageSnapshot
) -> tuple[bool, str]:
    """Confirm the observable result of an action (PRD §12.3)."""
    mode = action.spec.verification

    if mode is Verification.NONE:
        return True, ""

    if mode is Verification.URL_CHANGED:
        if after.url != before.url:
            return True, ""
        return False, f"url did not change from {before.url}"

    if mode is Verification.VALUE_READBACK:
        element = None
        original = before.by_index(action.target) if action.target is not None else None
        if original is not None:
            element = after.by_key(original.stable_key)
        if element is None:
            return False, "field vanished after writing to it"
        expected = action.value or ""
        if action.action_type is ActionType.CHECK:
            got = bool(element.value)
            want = expected.lower() not in ("", "false")
            if got is want:
                return True, ""
            return False, f"checkbox did not change to {want}"
        if (element.value or "") == expected:
            return True, ""
        return False, (
            f"value did not stick: wrote {expected!r}, read back "
            f"{element.value!r} — the field may be framework-controlled"
        )

    if mode is Verification.PAGE_CHANGED:
        if after.digest() != before.digest():
            return True, ""
        return False, "page did not change"

    if mode is Verification.FILENAME_VISIBLE:
        name = action.value or ""
        element = after.by_index(action.target) if action.target is not None else None
        if element is not None and name and name in (element.value or ""):
            return True, ""
        if name and name in after.text:
            return True, ""
        return False, f"uploaded file {name!r} is not shown on the page"

    if mode is Verification.CONFIRMATION_VISIBLE:
        if after.url != before.url or "submitted" in after.text.lower():
            return True, ""
        return False, "no confirmation appeared after submitting"

    return False, f"no verification strategy for {mode}"


class AgentLoop:
    """Drives a goal to completion, one verified action at a time."""

    def __init__(
        self,
        executor: Executor,
        decider: Decider,
        *,
        approval: ApprovalHook | None = None,
        step_cap: int = DEFAULT_STEP_CAP,
        kill_switch: KillSwitch | None = None,
        allow_submit_while_stubbed: bool = False,
    ) -> None:
        self.executor = executor
        self.decider = decider
        self.approval = approval
        self.budget = StepBudget(cap=step_cap)
        self.guard = LoopGuard()
        self.kill_switch = kill_switch or KillSwitch()
        self.allow_submit_while_stubbed = allow_submit_while_stubbed

    def run(self) -> RunResult:
        steps: list[Step] = []
        notes: list[str] = []

        while True:
            if self.kill_switch.stopped:
                return self._result(StopReason.KILLED, steps, notes)
            if self.budget.exhausted:
                notes.append(f"stopped after {self.budget.used} steps")
                return self._result(StopReason.STEP_CAP, steps, notes)

            before = self.executor.snapshot()
            chosen = self.decider.decide(before, list(notes))
            if not chosen:
                return self._result(StopReason.COMPLETED, steps, notes)

            # ONE action per turn, however many were offered.
            action = chosen[0]
            if len(chosen) > 1:
                log.debug(
                    "decider returned %d actions; taking only the first", len(chosen)
                )

            if action.is_terminal:
                return self._result(StopReason.COMPLETED, steps, notes)

            gate = self._gate(action, before)
            if gate is not None:
                notes.append(gate[1])
                return self._result(gate[0], steps, notes, pending=action)

            element = (
                before.by_index(action.target) if action.target is not None else None
            )
            signature = action.signature(element.stable_key if element else None)

            if self.guard.should_stop(signature):
                notes.append("giving up: the same action kept being requested")
                return self._result(StopReason.REPEATED, steps, notes)
            if self.guard.is_repeat(signature):
                # Nudge instead of repeating — the page did not respond last time.
                self.guard.record(signature)
                notes.append(self.guard.nudge_for(signature))
                continue

            # Check again immediately before acting. The user may have hit stop
            # while the decider was thinking, and firing the action anyway is
            # exactly what a kill switch is supposed to prevent.
            if self.kill_switch.stopped:
                return self._result(StopReason.KILLED, steps, notes, pending=action)

            self.guard.record(signature)
            self.budget.spend()

            step = self._perform(action, element, before)
            steps.append(step)
            if step.note:
                notes.append(step.note)

            if not step.performed:
                return self._result(StopReason.FAILED, steps, notes)

    # ── internals ────────────────────────────────────────────────────────

    def _gate(
        self, action: Action, snapshot: PageSnapshot
    ) -> tuple[StopReason, str] | None:
        """Refuse actions that must not proceed. None means allowed."""
        if (
            action.action_class is ActionClass.COMMITTING
            and is_stubbed()
            and not self.allow_submit_while_stubbed
        ):
            return (
                StopReason.BLOCKED,
                "refusing to submit while validation is stubbed — nothing may go "
                "out in the user's name unchecked (PRD §17.1)",
            )

        if action.needs_approval:
            if self.approval is None:
                return (
                    StopReason.AWAITING_APPROVAL,
                    f"{action.describe()} needs approval and no approver is attached",
                )
            if not self.approval(action, snapshot):
                return (
                    StopReason.AWAITING_APPROVAL,
                    f"{action.describe()} was not approved",
                )
        return None

    def _perform(self, action: Action, element, before: PageSnapshot) -> Step:
        try:
            self.executor.perform(action, element)
        except TargetNotFound as exc:
            return Step(
                action=action,
                performed=False,
                verified=False,
                note=f"target missing: {exc}",
                digest_before=before.digest(),
            )
        except ExecutionError as exc:
            return Step(
                action=action,
                performed=False,
                verified=False,
                note=f"action failed: {exc}",
                digest_before=before.digest(),
            )

        after = self.executor.snapshot()
        ok, why = verify(action, before, after)
        return Step(
            action=action,
            performed=True,
            verified=ok,
            note="" if ok else f"unverified: {why}",
            digest_before=before.digest(),
            digest_after=after.digest(),
        )

    def _result(
        self,
        reason: StopReason,
        steps: list[Step],
        notes: list[str],
        pending: Action | None = None,
    ) -> RunResult:
        return RunResult(
            reason=reason,
            steps=tuple(steps),
            notes=tuple(notes),
            pending_action=pending,
        )


class ScriptedDecider:
    """Replays a fixed list of actions. The test double for a model."""

    def __init__(self, actions: list[Action]) -> None:
        self.actions = list(actions)
        self.seen_notes: list[list[str]] = []

    def decide(self, snapshot: PageSnapshot, notes: list[str]) -> list[Action]:
        self.seen_notes.append(list(notes))
        return [self.actions.pop(0)] if self.actions else []
