"""Government and institutional forms (PRD §8.3).

The highest-stakes adapter, and the only one where being wrong can cost
somebody their immigration status rather than an interview. False statements on
official forms carry legal consequences, so every gate tightens:

======================  ==================  ================================
                        Standard            High-stakes
======================  ==================  ================================
Auto-fill threshold     0.80                0.95, otherwise ask
Prose generation        allowed             minimal — facts only
Approval                one gate            field-by-field acknowledgement
Cloud models            allowed for prose   blocked entirely
Evidence                screenshot          full record with hashes
======================  ==================  ================================

Field-by-field acknowledgement is the substantive difference. On a job
application, approving the whole form at once is reasonable. Here the user
confirms each value individually, because "I did not notice it had put the
wrong passport number in" is not a position anyone should be put in.

**Haru is not a lawyer or an immigration adviser.** :data:`DISCLAIMER` is
surfaced by this adapter and is not optional.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field

from haru.adapters.fields import HIGH_STAKES_THRESHOLD, FieldMapper
from haru.adapters.plan import ApplicationPlan, Disposition, build_plan
from haru.brain.fact_boundary import FactBoundary
from haru.cv.models import Ask
from haru.execution.page import PageSnapshot
from haru.models.router import ModelRouter
from haru.validation.types import ValidationMode

DISCLAIMER = (
    "Haru helps you fill this form. It is not a lawyer or an immigration "
    "adviser, cannot tell you whether you are eligible, and cannot tell you "
    "which form you need. Check anything that matters with someone qualified."
)

#: Hosts and patterns that mark a form as official.
OFFICIAL_SIGNALS: tuple[str, ...] = (
    ".gov", ".gov.uk", ".gc.ca", ".gov.au", ".gov.in", ".gov.bd",
    "europa.eu", "uscis", "hmrc", "irs.gov", "ircc", "consulate", "embassy",
)

#: Questions where a wrong answer is a false statement rather than a typo.
CRITICAL_PATTERNS: tuple[str, ...] = (
    "passport", "national insurance", "social security", "ssn", "nino",
    "date of birth", "place of birth", "nationality", "citizenship",
    "visa", "immigration", "criminal", "conviction", "previous name",
    "marital status", "dependant", "sponsor", "tax", "income", "declaration",
)


def looks_official(url: str, text: str = "") -> bool:
    lowered = f"{url} {text[:2000]}".lower()
    return any(signal in lowered for signal in OFFICIAL_SIGNALS)


def is_critical(label: str) -> bool:
    """Whether getting this field wrong is a false statement."""
    lowered = re.sub(r"[^a-z ]+", " ", label.lower())
    return any(pattern in lowered for pattern in CRITICAL_PATTERNS)


@dataclass
class HighStakesReview:
    """A plan that must be confirmed one field at a time."""

    plan: ApplicationPlan
    acknowledged: set[str] = dataclass_field(default_factory=set)

    # ── acknowledgement ──────────────────────────────────────────────────

    def acknowledge(self, label: str) -> bool:
        """Record that the user has checked this specific value."""
        if any(f.label == label for f in self.plan.to_fill):
            self.acknowledged.add(label)
            return True
        return False

    def acknowledge_all(self) -> int:
        """Deliberately not exposed in the UI — present for tests and scripts.

        A one-click "accept everything" on a passport form is exactly the
        pressure valve this mode exists to remove.
        """
        for entry in self.plan.to_fill:
            self.acknowledged.add(entry.label)
        return len(self.acknowledged)

    @property
    def pending(self) -> list:
        return [f for f in self.plan.to_fill if f.label not in self.acknowledged]

    @property
    def critical_fields(self) -> list:
        return [f for f in self.plan.to_fill if is_critical(f.label)]

    @property
    def progress(self) -> str:
        return f"{len(self.acknowledged)}/{len(self.plan.to_fill)} fields confirmed"

    # ── readiness ────────────────────────────────────────────────────────

    def blockers(self) -> list[str]:
        reasons = list(self.plan.blockers())
        for entry in self.pending:
            marker = " (critical)" if is_critical(entry.label) else ""
            reasons.append(f"not yet confirmed by you{marker}: {entry.label}")
        return reasons

    @property
    def is_submittable(self) -> bool:
        return not self.blockers()

    def preview(self) -> str:
        # Deliberately not ``plan.preview()``: that opens with a job-fit score,
        # which is meaningless on a visa form and actively confusing next to
        # "0/10 — no overlap" when there is nothing to match against.
        plan = self.plan
        lines = [DISCLAIMER, "", f"Official form — {plan.url or 'unknown'}", ""]

        if plan.to_fill:
            lines.append(f"Will be entered ({len(plan.to_fill)}):")
            lines.extend(f"  {f.label}: {f.match.value!r}" for f in plan.to_fill)
            lines.append("")
        if plan.to_ask:
            lines.append(f"Needs you ({len(plan.to_ask)}):")
            for entry in plan.to_ask:
                known = f" [on file: {entry.match.value!r}]" if entry.match.value else ""
                lines.append(f"  {entry.label}: {entry.reason}{known}")
            lines.append("")
        if plan.documents:
            lines.append("Documents: " + ", ".join(plan.documents))
            lines.append("")

        blockers = self.blockers()
        if blockers:
            lines.append("NOT READY TO SUBMIT:")
            lines.extend(f"  - {b}" for b in blockers)
            lines.append("")

        lines.append(self.progress)
        if self.pending:
            lines.append("Confirm each of these individually:")
            for entry in self.pending:
                mark = "!" if is_critical(entry.label) else "-"
                lines.append(f"  {mark} {entry.label}: {entry.match.value!r}")
        return "\n".join(lines)


def build_government_plan(
    snapshot: PageSnapshot,
    mapper: FieldMapper,
    boundary: FactBoundary,
    *,
    ask: Ask | None = None,
    router: ModelRouter | None = None,
    documents: list[str] | None = None,
) -> HighStakesReview:
    """Build a plan under high-stakes rules.

    ``router`` is switched into high-stakes mode if given, which blocks cloud
    models outright (PRD §13.2 rule 3) rather than relying on the caller to
    have configured it correctly.
    """
    if router is not None:
        router.high_stakes = True

    from haru.adapters.job import Fit

    plan = build_plan(
        snapshot,
        mapper,
        ask or Ask(),
        Fit(score=0.0, matched=(), missing=()),
        boundary,
        documents=documents,
        # No persuasive writing on an official form; anything generated is
        # checked at the strictest setting.
        generated=None,
        threshold=HIGH_STAKES_THRESHOLD,
        mode=ValidationMode.STRICT,
    )

    # A critical field is never auto-filled on confidence alone, and is always
    # labelled as critical — "Haru has no answer for this" is true but unhelpful
    # next to a passport number, where the user needs to know it matters.
    for index, entry in enumerate(plan.fields):
        if not is_critical(entry.label):
            continue
        if entry.disposition is Disposition.FILL and entry.match.confidence >= 1.0:
            continue
        # Don't restate it if the field's own rule already says so.
        reason = (
            entry.reason
            if "identity-critical" in entry.reason
            else f"identity-critical — confirm this yourself ({entry.reason})"
        )
        plan.fields[index] = type(entry)(
            element=entry.element,
            match=entry.match,
            disposition=Disposition.ASK,
            reason=reason,
        )

    return HighStakesReview(plan=plan)
