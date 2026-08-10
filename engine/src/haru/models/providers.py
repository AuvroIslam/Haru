"""Model backends (PRD §13.1).

All providers satisfy one protocol so the router can treat them alike. The
difference that matters is not the API shape but the trust boundary:

* **Local providers** take raw text. Nothing leaves the machine.
* **Cloud providers** take only a :class:`~haru.models.types.Redacted` prompt,
  and refuse anything else.

:class:`OllamaProvider` speaks Ollama's HTTP API. It is written against the
documented interface but has **not been exercised against a running Ollama** in
this repository — there is none installed here. The router's behaviour is
covered by tests using :class:`EchoProvider`; the Ollama request/response
mapping itself is unverified and should be checked on first real use.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

from haru.models.redact import is_redacted
from haru.models.types import (
    Redacted,
    Tier,
    UnredactedPrompt,
    Usage,
)

log = logging.getLogger(__name__)

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


@runtime_checkable
class Provider(Protocol):
    """Anything that can turn a prompt into text."""

    name: str
    tier: Tier

    def generate(self, prompt: str | Redacted, **options) -> tuple[str, Usage]:
        ...


class ProviderUnavailable(RuntimeError):
    """The backend could not be reached."""


class EchoProvider:
    """Deterministic local stand-in used in tests and as a fallback.

    Returns a canned reply, or echoes the prompt. Never raises, so the router
    can always be exercised without a model installed.
    """

    def __init__(
        self,
        name: str = "echo",
        tier: Tier = Tier.LOCAL_SMALL,
        replies: list[str] | None = None,
    ) -> None:
        self.name = name
        self.tier = tier
        self.replies = list(replies or [])
        self.calls: list[str] = []

    def generate(self, prompt: str | Redacted, **options) -> tuple[str, Usage]:
        text = prompt.text if isinstance(prompt, Redacted) else prompt
        self.calls.append(text)
        reply = self.replies.pop(0) if self.replies else f"echo: {text[:80]}"
        return reply, Usage(
            prompt_tokens=max(1, len(text) // 4),
            completion_tokens=max(1, len(reply) // 4),
        )


class OllamaProvider:
    """Local models via Ollama's HTTP API.

    Uses ``urllib`` rather than a client library: one fewer dependency, and the
    request is a single JSON POST.
    """

    def __init__(
        self,
        model: str,
        *,
        tier: Tier = Tier.LOCAL_SMALL,
        host: str = DEFAULT_OLLAMA_HOST,
        timeout: float = 120.0,
    ) -> None:
        self.name = f"ollama:{model}"
        self.model = model
        self.tier = tier
        self.host = host.rstrip("/")
        self.timeout = timeout

    def generate(self, prompt: str | Redacted, **options) -> tuple[str, Usage]:
        text = prompt.text if isinstance(prompt, Redacted) else prompt
        body = json.dumps(
            {
                "model": self.model,
                "prompt": text,
                "stream": False,
                "options": {"temperature": options.get("temperature", 0.2)},
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderUnavailable(
                f"could not reach Ollama at {self.host}: {exc}. "
                "Is it running? `ollama serve`"
            ) from exc

        return payload.get("response", ""), Usage(
            prompt_tokens=payload.get("prompt_eval_count", 0),
            completion_tokens=payload.get("eval_count", 0),
        )

    def is_available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=2.0):
                return True
        except Exception:  # noqa: BLE001
            return False


class CloudProvider:
    """Base for anything that sends text off the machine.

    Refuses a prompt that has not been through redaction. That check is the
    whole point of the class: it turns PRD §13.2 rule 1 from a convention into
    something that raises.
    """

    tier = Tier.CLOUD

    def __init__(self, name: str, *, cost_per_1k_prompt: float = 0.0,
                 cost_per_1k_completion: float = 0.0) -> None:
        self.name = name
        self.cost_per_1k_prompt = cost_per_1k_prompt
        self.cost_per_1k_completion = cost_per_1k_completion

    def generate(self, prompt: str | Redacted, **options) -> tuple[str, Usage]:
        if not is_redacted(prompt):
            raise UnredactedPrompt(
                f"{self.name} is a cloud provider and was handed raw text. "
                "Route it through haru.models.redact.redact() first."
            )
        assert isinstance(prompt, Redacted)
        return self._call(prompt, **options)

    def _call(self, prompt: Redacted, **options) -> tuple[str, Usage]:
        raise NotImplementedError

    def price(self, prompt_tokens: int, completion_tokens: int) -> float:
        return round(
            prompt_tokens / 1000 * self.cost_per_1k_prompt
            + completion_tokens / 1000 * self.cost_per_1k_completion,
            6,
        )


class ScriptedCloudProvider(CloudProvider):
    """Cloud provider for tests: enforces redaction, invents no network."""

    def __init__(self, replies: list[str] | None = None, **kwargs) -> None:
        super().__init__(kwargs.pop("name", "scripted-cloud"), **kwargs)
        self.replies = list(replies or [])
        self.received: list[Redacted] = []

    def _call(self, prompt: Redacted, **options) -> tuple[str, Usage]:
        self.received.append(prompt)
        reply = self.replies.pop(0) if self.replies else "cloud reply"
        prompt_tokens = max(1, len(prompt.text) // 4)
        completion_tokens = max(1, len(reply) // 4)
        return reply, Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=self.price(prompt_tokens, completion_tokens),
        )
