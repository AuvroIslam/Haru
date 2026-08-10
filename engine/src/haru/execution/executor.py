"""Executor protocol and an in-memory implementation for testing.

Browser control sits behind this protocol so the agent loop never owns a
browser and Browser Use never owns the loop (PRD §12.2, roadmap §1.4). The
Playwright implementation and the agent-fallback implementation both satisfy
this interface; the loop cannot tell them apart.

:class:`FakeExecutor` models a real form well enough to test the loop end to
end, including the failure mode that motivates post-action verification: a
field that accepts a write and silently does not keep it, exactly as a
React-controlled input does when written to naively (PRD §12.4).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from haru.execution.actions import Action, ActionType
from haru.execution.page import Element, ElementRole, PageSnapshot


class ExecutionError(RuntimeError):
    """The action could not be carried out."""


class TargetNotFound(ExecutionError):
    """The requested element index is not on the current page."""


@runtime_checkable
class Executor(Protocol):
    """Whatever actually drives the page."""

    def snapshot(self) -> PageSnapshot:
        """Read the current page state."""
        ...

    def perform(self, action: Action, element: Element | None) -> None:
        """Carry out one action. Raise :class:`ExecutionError` on failure."""
        ...


class FakeExecutor:
    """Scriptable in-memory page.

    ``framework_controlled`` names labels whose value silently fails to stick,
    reproducing the naive-write bug that post-action verification exists to
    catch.
    """

    def __init__(
        self,
        elements: list[Element],
        *,
        url: str = "https://example.test/apply",
        title: str = "Application",
        framework_controlled: set[str] | None = None,
        submit_confirms: bool = True,
    ) -> None:
        self._elements = {e.index: e for e in elements}
        self.url = url
        self.title = title
        self.framework_controlled = framework_controlled or set()
        self.submit_confirms = submit_confirms
        self.performed: list[Action] = []
        self.submitted = False
        self.uploads: dict[int, str] = {}
        self.screenshots = 0

    # ── protocol ─────────────────────────────────────────────────────────

    def snapshot(self) -> PageSnapshot:
        # Only a page that actually confirms says so. A form that swallowed the
        # submission looks unchanged, which is the case worth testing against.
        confirmed = self.submitted and self.submit_confirms
        text = "Application submitted" if confirmed else "Application form"
        return PageSnapshot(
            url=self.url,
            title=self.title,
            elements=tuple(self._elements[i] for i in sorted(self._elements)),
            text=text,
        )

    def perform(self, action: Action, element: Element | None) -> None:
        self.performed.append(action)

        if action.action_type is ActionType.NAVIGATE:
            self.url = action.url or self.url
            return
        if action.action_type in (ActionType.SCROLL, ActionType.WAIT, ActionType.EXTRACT, ActionType.DONE):
            return
        if action.action_type is ActionType.SCREENSHOT:
            self.screenshots += 1
            return

        if element is None:
            raise TargetNotFound(f"{action.action_type.value} needs a target")

        if element.disabled:
            raise ExecutionError(f"element [{element.index}] is disabled")

        if action.action_type is ActionType.FILL:
            self._write(element, action.value or "")
        elif action.action_type is ActionType.SELECT:
            if action.value not in element.options:
                raise ExecutionError(
                    f"{action.value!r} is not an option on [{element.index}]"
                )
            self._write(element, action.value or "")
        elif action.action_type is ActionType.CHECK:
            self._write(element, action.value or "true")
        elif action.action_type is ActionType.UPLOAD:
            self.uploads[element.index] = action.value or ""
            self._write(element, action.value or "")
        elif action.action_type is ActionType.CLICK:
            self._click(element)
        elif action.action_type is ActionType.SUBMIT:
            self.submitted = True
            if self.submit_confirms:
                self.url = self.url.rstrip("/") + "/confirmation"
                self.title = "Thank you"

    # ── internals ────────────────────────────────────────────────────────

    def _write(self, element: Element, value: str) -> None:
        if element.label in self.framework_controlled:
            return  # accepted, silently discarded — the bug we must detect
        self._elements[element.index] = element.model_copy(update={"value": value})

    def _click(self, element: Element) -> None:
        if element.role is ElementRole.CHECKBOX:
            flipped = "" if element.value else "true"
            self._elements[element.index] = element.model_copy(update={"value": flipped})
        elif element.role is ElementRole.LINK:
            self.url = self.url.rstrip("/") + "/next"

    # ── helpers for tests ────────────────────────────────────────────────

    def value_of(self, index: int) -> str | None:
        return self._elements[index].value

    def set_disabled(self, index: int, disabled: bool = True) -> None:
        el = self._elements[index]
        self._elements[index] = el.model_copy(update={"disabled": disabled})
