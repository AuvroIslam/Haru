"""Routing a task to the right model (PRD §13).

Policy, in one place:

* Each task has a default tier. Extraction, matching and classification — the
  bulk of the work — run locally.
* A cloud tier requires the user to have opted in, and is refused outright in
  high-stakes mode (PRD §8.3).
* Anything bound for the cloud is redacted first, and the call is logged with
  exactly what was sent, so the user can audit it.
* Spend is metered against a budget with a hard stop.

Degrading downward is deliberate: if the cloud is unavailable or disallowed, a
task falls back to a local tier rather than failing. Local output is worse at
prose, which the product says plainly rather than hiding (PRD §13.4) — but
worse output beats no output, and it always beats sending data the user did not
agree to send.
"""

from __future__ import annotations

import logging

from haru.brain.store import BrainStore
from haru.models.providers import Provider, ProviderUnavailable
from haru.models.redact import redact_for
from haru.models.types import (
    DEFAULT_TIERS,
    LOCAL_TIERS,
    BudgetExceeded,
    CloudCallRecord,
    CloudDisabled,
    ModelResponse,
    TaskKind,
    Tier,
    Usage,
)

log = logging.getLogger(__name__)

#: Order to fall back through when a tier is unavailable.
_FALLBACK: dict[Tier, tuple[Tier, ...]] = {
    Tier.CLOUD: (Tier.LOCAL_LARGE, Tier.LOCAL_SMALL),
    Tier.LOCAL_LARGE: (Tier.LOCAL_SMALL,),
    Tier.LOCAL_SMALL: (),
    Tier.EMBEDDING: (),
    Tier.DETERMINISTIC: (),
}


class ModelRouter:
    """Chooses where each task runs, and keeps the receipts."""

    def __init__(
        self,
        providers: dict[Tier, Provider] | None = None,
        *,
        store: BrainStore | None = None,
        allow_cloud: bool = False,
        high_stakes: bool = False,
        budget_usd: float | None = None,
        overrides: dict[TaskKind, Tier] | None = None,
    ) -> None:
        self.providers = dict(providers or {})
        self.store = store
        #: Cloud is opt-in. The product is fully usable without it (P6).
        self.allow_cloud = allow_cloud
        #: High-stakes mode blocks cloud entirely (PRD §8.3).
        self.high_stakes = high_stakes
        self.budget_usd = budget_usd
        self.overrides = dict(overrides or {})
        self.spent = Usage()
        self.cloud_calls: list[CloudCallRecord] = []

    # ── policy ───────────────────────────────────────────────────────────

    def tier_for(self, task: TaskKind) -> Tier:
        return self.overrides.get(task, DEFAULT_TIERS[task])

    def cloud_permitted(self) -> bool:
        return self.allow_cloud and not self.high_stakes

    def resolve(self, task: TaskKind) -> Tier:
        """The tier this task will actually use, after policy and availability."""
        wanted = self.tier_for(task)
        if wanted is Tier.CLOUD and not self.cloud_permitted():
            wanted = self._first_available(_FALLBACK[Tier.CLOUD]) or Tier.LOCAL_SMALL
        if wanted in self.providers:
            return wanted
        return self._first_available(_FALLBACK.get(wanted, ())) or wanted

    def _first_available(self, tiers: tuple[Tier, ...]) -> Tier | None:
        return next((t for t in tiers if t in self.providers), None)

    # ── running ──────────────────────────────────────────────────────────

    def run(self, task: TaskKind, prompt: str, **options) -> ModelResponse:
        """Send a task to whichever provider policy allows."""
        tier = self.resolve(task)
        provider = self.providers.get(tier)
        if provider is None:
            # Say *why* rather than reporting a missing local provider: when
            # policy blocked the cloud and there is nothing local to fall back
            # to, "no provider for t1" hides the actual cause from the user.
            if self.tier_for(task) is Tier.CLOUD and not self.cloud_permitted():
                raise CloudDisabled(
                    "high-stakes mode blocks cloud models, and no local model is "
                    "configured to fall back to"
                    if self.high_stakes
                    else "cloud models are not enabled, and no local model is "
                    "configured to fall back to"
                )
            raise ProviderUnavailable(
                f"no provider configured for {tier.value} (task {task.value})"
            )

        if tier is Tier.CLOUD:
            return self._run_cloud(task, provider, prompt, **options)

        text, usage = provider.generate(prompt, **options)
        self.spent = self.spent + usage
        return ModelResponse(text=text, tier=tier, model=provider.name, usage=usage)

    def _run_cloud(
        self, task: TaskKind, provider: Provider, prompt: str, **options
    ) -> ModelResponse:
        if not self.cloud_permitted():
            raise CloudDisabled(
                "high-stakes mode blocks cloud models"
                if self.high_stakes
                else "cloud models are not enabled"
            )

        payload = (
            redact_for(prompt, self.store) if self.store is not None else _redact_plain(prompt)
        )

        if self.budget_usd is not None and self.spent.cost_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"spent ${self.spent.cost_usd:.4f} of ${self.budget_usd:.2f} budget"
            )

        text, usage = provider.generate(payload, **options)
        self.spent = self.spent + usage

        self.cloud_calls.append(
            CloudCallRecord(
                task=task,
                model=provider.name,
                prompt=payload.text,
                redacted_fields=tuple(payload.removed),
                usage=usage,
            )
        )

        if self.budget_usd is not None and self.spent.cost_usd > self.budget_usd:
            log.warning(
                "budget exceeded after this call: $%.4f of $%.2f",
                self.spent.cost_usd,
                self.budget_usd,
            )
        return ModelResponse(text=text, tier=Tier.CLOUD, model=provider.name, usage=usage)

    # ── reporting ────────────────────────────────────────────────────────

    @property
    def ran_entirely_locally(self) -> bool:
        return not self.cloud_calls

    def cost_summary(self) -> str:
        if self.spent.cost_usd == 0:
            return f"{self.spent.total_tokens} tokens — $0.00, ran locally"
        return (
            f"{self.spent.total_tokens} tokens — ${self.spent.cost_usd:.4f} "
            f"across {len(self.cloud_calls)} cloud call(s)"
        )

    def audit(self) -> list[dict]:
        """Exactly what left the machine (PRD §13.2 rule 4)."""
        return [
            {
                "task": call.task.value,
                "model": call.model,
                "prompt": call.prompt,
                "redacted": list(call.redacted_fields),
                "cost_usd": call.usage.cost_usd,
            }
            for call in self.cloud_calls
        ]


def _redact_plain(prompt: str):
    from haru.models.redact import redact

    return redact(prompt)


def probe_local(host: str | None = None) -> list[str]:
    """Which local models are installed, if any.

    Used at setup to pick a working configuration rather than asking the user
    to guess (PRD §13.1).
    """
    import json
    import urllib.request

    from haru.models.providers import DEFAULT_OLLAMA_HOST

    base = (host or DEFAULT_OLLAMA_HOST).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - absence is the normal case
        return []
    return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
