"""Model routing vocabulary (PRD §13).

Free by default, better if you pay, never at the cost of privacy.

The type that carries weight here is :class:`Redacted`. Cloud providers accept
*only* a ``Redacted`` prompt, and a ``Redacted`` can only be produced by
:func:`haru.models.redact.redact`. That makes "raw Brain PII never goes to a
cloud model" (PRD §13.2 rule 1) a property of the type system rather than a
rule someone has to remember at every call site.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from haru.brain.provenance import utcnow


class Tier(str, Enum):
    """Where a task runs. Ordered cheapest and most private first."""

    DETERMINISTIC = "t0"  # no model at all
    LOCAL_SMALL = "t1"  # 3–8B: classification, extraction, matching
    LOCAL_LARGE = "t2"  # 14B+: prose drafts, reasoning
    CLOUD = "t3"  # opt-in, never sees raw PII
    EMBEDDING = "e"  # always local


LOCAL_TIERS: frozenset[Tier] = frozenset(
    {Tier.DETERMINISTIC, Tier.LOCAL_SMALL, Tier.LOCAL_LARGE, Tier.EMBEDDING}
)


class TaskKind(str, Enum):
    """What the model is being asked to do. Determines the default tier."""

    CLASSIFY = "classify"
    EXTRACT = "extract"
    MATCH_FIELD = "match_field"
    PARSE_FORM = "parse_form"
    DECIDE_ACTION = "decide_action"
    SCORE_FIT = "score_fit"
    DRAFT_PROSE = "draft_prose"
    POLISH_PROSE = "polish_prose"
    EMBED = "embed"


#: Default tier per task. Extraction and matching are the bulk of the work and
#: run locally; only prose polish reaches for a frontier model, and only when
#: the user has opted in.
DEFAULT_TIERS: dict[TaskKind, Tier] = {
    TaskKind.CLASSIFY: Tier.LOCAL_SMALL,
    TaskKind.EXTRACT: Tier.LOCAL_SMALL,
    TaskKind.MATCH_FIELD: Tier.LOCAL_SMALL,
    TaskKind.PARSE_FORM: Tier.LOCAL_SMALL,
    TaskKind.DECIDE_ACTION: Tier.LOCAL_LARGE,
    TaskKind.SCORE_FIT: Tier.LOCAL_LARGE,
    TaskKind.DRAFT_PROSE: Tier.LOCAL_LARGE,
    TaskKind.POLISH_PROSE: Tier.CLOUD,
    TaskKind.EMBED: Tier.EMBEDDING,
}


class Redacted(BaseModel):
    """A prompt with sensitive values removed, safe to leave the machine.

    Constructed only by :func:`haru.models.redact.redact`; the private marker
    is checked on the way out to a cloud provider. This is not tamper-proof
    against someone determined to bypass it — it is a guard rail that makes the
    unsafe path require obvious, deliberate effort.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    #: What was scrubbed, by placeholder, so the user can audit a cloud call.
    removed: dict[str, str] = Field(default_factory=dict)
    marker: str = ""

    @property
    def had_sensitive_content(self) -> bool:
        return bool(self.removed)


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 6),
        )


class ModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    tier: Tier
    model: str
    usage: Usage = Field(default_factory=Usage)

    @property
    def was_local(self) -> bool:
        return self.tier in LOCAL_TIERS


class CloudCallRecord(BaseModel):
    """An audit entry for every request that left the machine (PRD §13.2 rule 4)."""

    model_config = ConfigDict(frozen=True)

    at: object = Field(default_factory=utcnow)
    task: TaskKind
    model: str
    prompt: str
    redacted_fields: tuple[str, ...] = ()
    usage: Usage = Field(default_factory=Usage)


class BudgetExceeded(Exception):
    """The configured spend limit would be passed by this call."""


class CloudDisabled(Exception):
    """A cloud tier was requested but is not permitted right now."""


class UnredactedPrompt(Exception):
    """Raw text was about to be sent to a cloud provider."""
