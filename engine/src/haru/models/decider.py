"""A model that chooses the next action (PRD §12.2, §12.5).

The model never writes a selector and never writes code. It picks one action
from the registry and names its target by index. Both constraints matter:

* An invented CSS selector matches nothing and fails silently. An invented
  index either resolves or is rejected here.
* An action type outside the registry has no declared class, so it would skip
  the approval gate. Parsing rejects unknown types rather than guessing.

The model is asked for one action, and :class:`~haru.execution.loop.AgentLoop`
takes only the first regardless — belt and braces, because a model that returns
a plan will otherwise have that plan executed against a stale page.
"""

from __future__ import annotations

import json
import logging
import re

from haru.execution.actions import ACTION_SPECS, Action, ActionClass, ActionType
from haru.execution.page import PageSnapshot
from haru.models.router import ModelRouter
from haru.models.types import TaskKind

log = logging.getLogger(__name__)

_JSON = re.compile(r"\{.*\}", re.S)

SYSTEM_PROMPT = """\
You operate a web form on behalf of a person. Choose exactly ONE next action.

Rules:
- Refer to elements only by their [index] from the list. Never write a CSS selector.
- Choose one action per turn. The page is re-read after every action.
- Do not invent values. Use only values given to you.
- When the form is complete, choose "done". Never choose "submit" unless
  explicitly instructed; submission requires human approval.

Reply with JSON only:
{"action": "<type>", "target": <index or null>, "value": "<text or null>", "reason": "<short>"}

Available actions: %s
"""


def describe_actions() -> str:
    return ", ".join(
        f"{t.value}"
        for t, spec in ACTION_SPECS.items()
        if spec.action_class is not ActionClass.COMMITTING
    )


def build_prompt(
    snapshot: PageSnapshot, goal: str, notes: list[str], values: dict[str, str] | None
) -> str:
    parts = [
        SYSTEM_PROMPT % describe_actions(),
        f"\nGOAL: {goal}",
        f"\nPAGE:\n{snapshot.describe(limit=60)}",
    ]
    if values:
        parts.append(
            "\nVALUES YOU MAY USE:\n"
            + "\n".join(f"  {k}: {v}" for k, v in values.items())
        )
    if notes:
        parts.append("\nNOTES FROM PREVIOUS STEPS:\n" + "\n".join(f"  - {n}" for n in notes[-5:]))
    return "\n".join(parts)


class ActionParseError(ValueError):
    """The model's reply could not be turned into a valid action."""


def parse_action(reply: str, snapshot: PageSnapshot) -> Action:
    """Turn a model reply into a validated action.

    Rejects unknown action types, committing actions, and targets that are not
    on the page. Every rejection is a case where executing anyway would be
    worse than stopping.
    """
    match = _JSON.search(reply)
    if not match:
        raise ActionParseError(f"no JSON object in reply: {reply[:120]!r}")

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ActionParseError(f"invalid JSON: {exc}") from exc

    raw_type = str(payload.get("action", "")).strip().lower()
    try:
        action_type = ActionType(raw_type)
    except ValueError:
        raise ActionParseError(f"unknown action type {raw_type!r}") from None

    if ACTION_SPECS[action_type].action_class is ActionClass.COMMITTING:
        raise ActionParseError(
            f"{raw_type} is a committing action and cannot be chosen by a model"
        )

    target = payload.get("target")
    if target is not None:
        try:
            target = int(target)
        except (TypeError, ValueError):
            raise ActionParseError(f"target {target!r} is not an index") from None
        if snapshot.by_index(target) is None:
            raise ActionParseError(f"no element [{target}] on this page")

    value = payload.get("value")
    return Action(
        action_type=action_type,
        target=target,
        value=None if value in (None, "") else str(value),
        url=payload.get("url"),
        reason=str(payload.get("reason", ""))[:200],
    )


class ModelDecider:
    """Asks a model what to do next, and refuses to act on a bad answer."""

    def __init__(
        self,
        router: ModelRouter,
        goal: str,
        *,
        values: dict[str, str] | None = None,
        max_retries: int = 2,
    ) -> None:
        self.router = router
        self.goal = goal
        self.values = dict(values or {})
        self.max_retries = max_retries
        self.failures: list[str] = []

    def decide(self, snapshot: PageSnapshot, notes: list[str]) -> list[Action]:
        working_notes = list(notes)

        for attempt in range(self.max_retries + 1):
            prompt = build_prompt(snapshot, self.goal, working_notes, self.values)
            response = self.router.run(TaskKind.DECIDE_ACTION, prompt)
            try:
                return [parse_action(response.text, snapshot)]
            except ActionParseError as exc:
                self.failures.append(str(exc))
                log.debug("unusable reply (attempt %d): %s", attempt + 1, exc)
                # Tell the model what was wrong rather than retrying blind.
                working_notes = working_notes + [f"Your last reply was rejected: {exc}"]

        # Out of retries: stop rather than act on something unparsed.
        log.warning("decider gave up after %d attempts", self.max_retries + 1)
        return []
