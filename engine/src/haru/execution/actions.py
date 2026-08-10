"""The action registry (PRD §12.5, §14.1).

The decider chooses from a fixed set of typed actions rather than emitting code
or selectors. Each action declares three things the rest of the system needs:

* **its class** — free, reversible, committing or sensitive, which decides
  whether a human must approve it before it runs (PRD §14.1);
* **how to verify it landed** — an unverified action counts as failed (§12.3);
* **whether it can be undone**.

Declaring these on the action rather than at call sites means a new action type
cannot quietly skip an approval gate: it has no default class, so registering it
forces the decision.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionType(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    CHECK = "check"
    SCROLL = "scroll"
    UPLOAD = "upload"
    SCREENSHOT = "screenshot"
    EXTRACT = "extract"
    WAIT = "wait"
    SUBMIT = "submit"
    DONE = "done"


class ActionClass(str, Enum):
    """PRD §14.1. Determines the gate, not the mechanism."""

    FREE = "free"
    REVERSIBLE = "reversible"
    COMMITTING = "committing"
    SENSITIVE = "sensitive"


class Verification(str, Enum):
    """How we confirm the action actually happened (PRD §12.3)."""

    NONE = "none"
    VALUE_READBACK = "value_readback"
    PAGE_CHANGED = "page_changed"
    URL_CHANGED = "url_changed"
    FILENAME_VISIBLE = "filename_visible"
    CONFIRMATION_VISIBLE = "confirmation_visible"


class ActionSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_type: ActionType
    action_class: ActionClass
    verification: Verification
    reversible: bool
    needs_target: bool
    description: str


#: The whole vocabulary. Adding an entry is a deliberate act — the missing
#: fields have no defaults, so a new action cannot inherit a permissive class.
ACTION_SPECS: dict[ActionType, ActionSpec] = {
    ActionType.NAVIGATE: ActionSpec(
        action_type=ActionType.NAVIGATE,
        action_class=ActionClass.FREE,
        verification=Verification.URL_CHANGED,
        reversible=True,
        needs_target=False,
        description="Go to a URL",
    ),
    ActionType.CLICK: ActionSpec(
        action_type=ActionType.CLICK,
        action_class=ActionClass.FREE,
        verification=Verification.PAGE_CHANGED,
        reversible=False,
        needs_target=True,
        description="Click an element",
    ),
    ActionType.FILL: ActionSpec(
        action_type=ActionType.FILL,
        action_class=ActionClass.REVERSIBLE,
        verification=Verification.VALUE_READBACK,
        reversible=True,
        needs_target=True,
        description="Type into a field",
    ),
    ActionType.SELECT: ActionSpec(
        action_type=ActionType.SELECT,
        action_class=ActionClass.REVERSIBLE,
        verification=Verification.VALUE_READBACK,
        reversible=True,
        needs_target=True,
        description="Choose a dropdown option",
    ),
    ActionType.CHECK: ActionSpec(
        action_type=ActionType.CHECK,
        action_class=ActionClass.REVERSIBLE,
        verification=Verification.VALUE_READBACK,
        reversible=True,
        needs_target=True,
        description="Tick or untick a box",
    ),
    ActionType.SCROLL: ActionSpec(
        action_type=ActionType.SCROLL,
        action_class=ActionClass.FREE,
        verification=Verification.NONE,
        reversible=True,
        needs_target=False,
        description="Scroll the page",
    ),
    ActionType.UPLOAD: ActionSpec(
        action_type=ActionType.UPLOAD,
        action_class=ActionClass.SENSITIVE,
        verification=Verification.FILENAME_VISIBLE,
        reversible=True,
        needs_target=True,
        description="Attach a file",
    ),
    ActionType.SCREENSHOT: ActionSpec(
        action_type=ActionType.SCREENSHOT,
        action_class=ActionClass.FREE,
        verification=Verification.NONE,
        reversible=True,
        needs_target=False,
        description="Capture the page",
    ),
    ActionType.EXTRACT: ActionSpec(
        action_type=ActionType.EXTRACT,
        action_class=ActionClass.FREE,
        verification=Verification.NONE,
        reversible=True,
        needs_target=False,
        description="Read content from the page",
    ),
    ActionType.WAIT: ActionSpec(
        action_type=ActionType.WAIT,
        action_class=ActionClass.FREE,
        verification=Verification.NONE,
        reversible=True,
        needs_target=False,
        description="Pause for the page to settle",
    ),
    ActionType.SUBMIT: ActionSpec(
        action_type=ActionType.SUBMIT,
        action_class=ActionClass.COMMITTING,
        verification=Verification.CONFIRMATION_VISIBLE,
        reversible=False,
        needs_target=True,
        description="Submit the form",
    ),
    ActionType.DONE: ActionSpec(
        action_type=ActionType.DONE,
        action_class=ActionClass.FREE,
        verification=Verification.NONE,
        reversible=True,
        needs_target=False,
        description="Finish the task",
    ),
}


class Action(BaseModel):
    """One step the decider wants taken."""

    model_config = ConfigDict(frozen=True)

    action_type: ActionType
    #: Index from the current snapshot — never a selector (PRD §12.2).
    target: int | None = None
    value: str | None = None
    url: str | None = None
    reason: str = ""

    @model_validator(mode="after")
    def _target_matches_spec(self) -> Action:
        if self.spec.needs_target and self.target is None:
            raise ValueError(f"{self.action_type.value} requires a target index")
        if self.action_type is ActionType.NAVIGATE and not self.url:
            raise ValueError("navigate requires a url")
        return self

    @property
    def spec(self) -> ActionSpec:
        return ACTION_SPECS[self.action_type]

    @property
    def action_class(self) -> ActionClass:
        return self.spec.action_class

    @property
    def needs_approval(self) -> bool:
        """Committing and sensitive actions never run unattended (PRD §14.1)."""
        return self.action_class in (ActionClass.COMMITTING, ActionClass.SENSITIVE)

    @property
    def is_terminal(self) -> bool:
        return self.action_type is ActionType.DONE

    def signature(self, stable_key: str | None = None) -> str:
        """Identity for loop detection.

        Keyed on the element's stable key rather than its index, so a re-render
        that renumbers the page does not disguise a repeat (PRD §12.6).
        """
        return f"{self.action_type.value}:{stable_key or self.target}:{self.value or ''}"

    def describe(self) -> str:
        bits = [self.action_type.value]
        if self.target is not None:
            bits.append(f"[{self.target}]")
        if self.value:
            bits.append(repr(self.value))
        if self.url:
            bits.append(self.url)
        return " ".join(bits)


def committing_types() -> frozenset[ActionType]:
    return frozenset(
        t for t, s in ACTION_SPECS.items() if s.action_class is ActionClass.COMMITTING
    )
