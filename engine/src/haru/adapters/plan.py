"""The application plan and its approval preview (PRD §14.2).

An approval gate is only meaningful if the user can see what they are
approving. "Submit this application?" with a yes/no button is not consent; it
is a rubber stamp. So the plan enumerates every value that will be entered,
every document that will be attached, and everything Haru is unsure about,
before anything is typed into a form.

The plan is also where the safety rules converge. It is *not submittable* while
any of these hold:

* a required field has no answer;
* generated text failed the fact boundary;
* a sensitive field has not been explicitly decided;
* validation is still stubbed (PRD §17.1).

Each is reported separately, because "not ready" without a reason is not
actionable.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import Enum

from haru.adapters.fields import STANDARD_THRESHOLD, FieldMapper, FieldMatch
from haru.adapters.job import Fit
from haru.brain.fact_boundary import FactBoundary
from haru.cv.models import Ask, TailoredCV
from haru.execution.actions import Action, ActionType
from haru.execution.page import Element, PageSnapshot
from haru.validation.seam import is_stubbed, validate
from haru.validation.types import Artifact, ArtifactKind, ValidationMode, Violation


class Disposition(str, Enum):
    """What Haru intends to do with one field."""

    FILL = "fill"
    ASK = "ask"
    SKIP = "skip"


@dataclass(frozen=True)
class FieldPlan:
    element: Element
    match: FieldMatch
    disposition: Disposition
    reason: str

    @property
    def label(self) -> str:
        return self.element.label or self.match.label

    def describe(self) -> str:
        if self.disposition is Disposition.FILL:
            return f"{self.label}: {self.match.value!r}"
        return f"{self.label}: {self.reason}"


@dataclass
class ApplicationPlan:
    """Everything that will happen, assembled before anything happens."""

    ask: Ask
    fit: Fit
    url: str = ""
    fields: list[FieldPlan] = dataclass_field(default_factory=list)
    cv: TailoredCV | None = None
    documents: list[str] = dataclass_field(default_factory=list)
    generated: dict[str, str] = dataclass_field(default_factory=dict)
    violations: list[Violation] = dataclass_field(default_factory=list)

    # ── views ────────────────────────────────────────────────────────────

    @property
    def to_fill(self) -> list[FieldPlan]:
        return [f for f in self.fields if f.disposition is Disposition.FILL]

    @property
    def to_ask(self) -> list[FieldPlan]:
        return [f for f in self.fields if f.disposition is Disposition.ASK]

    @property
    def unanswered_required(self) -> list[FieldPlan]:
        return [f for f in self.to_ask if f.element.required]

    @property
    def sensitive_pending(self) -> list[FieldPlan]:
        return [f for f in self.to_ask if f.match.sensitive]

    # ── readiness ────────────────────────────────────────────────────────

    def blockers(self) -> list[str]:
        """Every reason this cannot be submitted yet."""
        reasons: list[str] = []
        if is_stubbed():
            reasons.append(
                "validation is stubbed — nothing may be submitted unchecked"
            )
        for violation in self.violations:
            reasons.append(f"generated text blocked: {violation}")
        for plan in self.unanswered_required:
            reasons.append(f"required field unanswered: {plan.label}")
        for plan in self.sensitive_pending:
            reasons.append(f"needs your decision: {plan.label}")
        return reasons

    @property
    def is_submittable(self) -> bool:
        return not self.blockers()

    # ── output ───────────────────────────────────────────────────────────

    def actions(self) -> list[Action]:
        """The fill actions this plan authorises. Never includes a submit.

        Submission stays a separate, explicitly approved step (PRD §14.1).
        """
        return [
            Action(
                action_type=ActionType.FILL,
                target=plan.element.index,
                value=plan.match.value,
                reason=f"{plan.match.canonical} ({plan.match.confidence:.0%})",
            )
            for plan in self.to_fill
        ]

    def preview(self) -> str:
        """What the user reads before approving."""
        lines = [
            f"Application — {self.ask.role or 'role'} at {self.ask.org or 'company'}",
            f"Fit: {self.fit.summary()}",
            "",
        ]
        if self.to_fill:
            lines.append(f"Will fill ({len(self.to_fill)}):")
            lines.extend(f"  {p.describe()}" for p in self.to_fill)
            lines.append("")
        if self.to_ask:
            lines.append(f"Needs you ({len(self.to_ask)}):")
            lines.extend(f"  {p.describe()}" for p in self.to_ask)
            lines.append("")
        if self.documents:
            lines.append("Documents: " + ", ".join(self.documents))
            lines.append("")
        if self.generated:
            lines.append("Generated:")
            for name, text in self.generated.items():
                preview = text if len(text) <= 120 else text[:117] + "…"
                lines.append(f"  {name}: {preview}")
            lines.append("")

        blockers = self.blockers()
        if blockers:
            lines.append("NOT READY TO SUBMIT:")
            lines.extend(f"  - {b}" for b in blockers)
        else:
            lines.append("Ready to submit once you approve.")
        return "\n".join(lines)


def build_plan(
    snapshot: PageSnapshot,
    mapper: FieldMapper,
    ask: Ask,
    fit: Fit,
    boundary: FactBoundary,
    *,
    cv: TailoredCV | None = None,
    generated: dict[str, str] | None = None,
    documents: list[str] | None = None,
    threshold: float = STANDARD_THRESHOLD,
    mode: ValidationMode = ValidationMode.NORMAL,
) -> ApplicationPlan:
    """Decide, for every field on the page, what to do with it."""
    plan = ApplicationPlan(
        ask=ask,
        fit=fit,
        url=snapshot.url,
        cv=cv,
        documents=list(documents or []),
        generated=dict(generated or {}),
    )

    for element in snapshot.elements:
        if not element.holds_value or element.disabled:
            continue

        match = mapper.match(element.label)

        if match.always_ask:
            disposition, reason = Disposition.ASK, (
                match.note or "needs your explicit decision"
            )
        elif match.is_unknown:
            disposition, reason = Disposition.ASK, "Haru has no answer for this"
        elif match.is_auto_fillable(threshold):
            disposition, reason = Disposition.FILL, match.source
        else:
            disposition, reason = Disposition.ASK, (
                f"only {match.confidence:.0%} confident — not guessing"
            )

        if disposition is Disposition.ASK and not element.required and match.is_unknown:
            # Optional and unrecognised: mention it, don't demand it.
            disposition = Disposition.SKIP
            reason = "optional and unrecognised — left blank"

        plan.fields.append(
            FieldPlan(element=element, match=match, disposition=disposition, reason=reason)
        )

    # Every generated artifact passes the fact boundary before it can be used.
    for name, text in plan.generated.items():
        result = validate(
            Artifact(
                kind=ArtifactKind.APPLICATION_ANSWER,
                text=text,
                context={"question": name},
            ),
            boundary,
            mode,
        )
        plan.violations.extend(result.blocking)

    return plan
