"""Hackathon submissions (PRD §8.2).

Devpost asks for the same seven story blocks every time. Haru drafts them from
the repository and the user's notes, then puts every one through repo-grounded
validation before it can be used.

The ordering is the point. Generation is cheap and a model will happily write
that the project "leverages Kafka for real-time streaming" because that sounds
like a hackathon project. Validation against the actual manifest is what makes
the output worth submitting — judges check, and an inflated write-up is worse
than a modest accurate one.

Blocked sections are returned as blocked, with the reason. They are never
quietly dropped or silently rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from haru.adapters.repo import RepoFacts
from haru.brain.fact_boundary import FactBoundary
from haru.models.router import ModelRouter
from haru.models.types import TaskKind
from haru.validation.grounding import Omission, RepoGroundedValidator
from haru.validation.types import Artifact, ArtifactKind, ValidationMode, Violation


class Section(str, Enum):
    """Devpost's standard story blocks, in the order the form presents them."""

    TAGLINE = "tagline"
    INSPIRATION = "inspiration"
    WHAT_IT_DOES = "what_it_does"
    HOW_WE_BUILT_IT = "how_we_built_it"
    CHALLENGES = "challenges"
    ACCOMPLISHMENTS = "accomplishments"
    WHAT_WE_LEARNED = "what_we_learned"
    WHATS_NEXT = "whats_next"


SECTION_PROMPTS: dict[Section, str] = {
    Section.TAGLINE: "One sentence, under 20 words, describing what it is. No hype.",
    Section.INSPIRATION: "Two or three sentences on the problem that prompted this.",
    Section.WHAT_IT_DOES: "Three or four sentences on what it actually does today.",
    Section.HOW_WE_BUILT_IT: "Describe the architecture using ONLY the technologies listed as present.",
    Section.CHALLENGES: "Two or three specific technical problems and how they were handled.",
    Section.ACCOMPLISHMENTS: "Two or three things that genuinely work, stated plainly.",
    Section.WHAT_WE_LEARNED: "Two or three concrete lessons.",
    Section.WHATS_NEXT: "Two or three honest next steps, including what is unfinished.",
}

PROMPT_TEMPLATE = """\
Write the "{title}" section of a hackathon submission.

{instruction}

PROJECT: {name}
TECHNOLOGIES ACTUALLY PRESENT IN THE REPOSITORY: {evidence}
{scale}
{notes}
Rules:
- Use ONLY technologies from the list above. Do not mention any other tool,
  framework or service as something this project uses.
- Do not invent metrics, user numbers, or performance figures.
- Write plainly. No marketing language, no superlatives.
- Return only the section text. No heading, no preamble, no commentary.
"""


@dataclass
class DraftedSection:
    section: Section
    text: str
    blocked: tuple[Violation, ...] = ()

    @property
    def is_usable(self) -> bool:
        return bool(self.text) and not self.blocked


@dataclass
class Submission:
    """A drafted hackathon submission, section by section."""

    repo: RepoFacts
    sections: dict[Section, DraftedSection] = field(default_factory=dict)
    omissions: list[Omission] = field(default_factory=list)

    @property
    def usable(self) -> dict[Section, str]:
        return {s: d.text for s, d in self.sections.items() if d.is_usable}

    @property
    def blocked(self) -> dict[Section, tuple[Violation, ...]]:
        return {s: d.blocked for s, d in self.sections.items() if d.blocked}

    @property
    def is_complete(self) -> bool:
        return bool(self.sections) and not self.blocked

    def preview(self) -> str:
        lines = [f"Submission — {self.repo.name}", self.repo.summary(), ""]
        for section, draft in self.sections.items():
            title = section.value.replace("_", " ").title()
            lines.append(f"## {title}")
            if draft.blocked:
                lines.append("  BLOCKED:")
                lines.extend(f"    - {v}" for v in draft.blocked)
            else:
                lines.append(f"  {draft.text}")
            lines.append("")
        if self.omissions:
            lines.append("Present in the repo but unmentioned:")
            lines.extend(f"  - {o}" for o in self.omissions)
        return "\n".join(lines)


def build_prompt(
    section: Section, repo: RepoFacts, notes: str = "", team: tuple[str, ...] = ()
) -> str:
    scale = f"SCALE: {repo.file_count} files, {repo.code_lines:,} lines"
    if repo.has_tests:
        scale += ", with tests"
    note_block = f"NOTES FROM THE AUTHOR: {notes}\n" if notes else ""
    if team:
        note_block += f"TEAM: {', '.join(team)}\n"

    return PROMPT_TEMPLATE.format(
        title=section.value.replace("_", " ").title(),
        instruction=SECTION_PROMPTS[section],
        name=repo.name,
        evidence=", ".join(sorted(repo.evidence)) or "none detected",
        scale=scale,
        notes=note_block,
    )


def draft(
    repo: RepoFacts,
    router: ModelRouter,
    boundary: FactBoundary,
    *,
    sections: tuple[Section, ...] = tuple(Section),
    notes: str = "",
    team: tuple[str, ...] = (),
    event: str | None = None,
    mode: ValidationMode = ValidationMode.NORMAL,
    max_attempts: int = 2,
) -> Submission:
    """Draft a submission and validate every section against the repository.

    A section that fails validation is regenerated once with the violation fed
    back, then reported as blocked. It is never silently kept.
    """
    validator = RepoGroundedValidator(repo, team=team, event=event)
    submission = Submission(repo=repo)

    for section in sections:
        prompt = build_prompt(section, repo, notes, team)
        drafted = DraftedSection(section=section, text="")

        for attempt in range(max_attempts):
            response = router.run(TaskKind.DRAFT_PROSE, prompt)
            text = response.text.strip()
            result = validator.validate(
                Artifact(
                    kind=ArtifactKind.HACKATHON_STORY,
                    text=text,
                    context={"section": section.value},
                ),
                boundary,
                mode,
            )
            drafted = DraftedSection(
                section=section, text=text, blocked=tuple(result.blocking)
            )
            if result.passed:
                break
            # Tell the model exactly what was wrong rather than retrying blind.
            prompt = (
                build_prompt(section, repo, notes, team)
                + "\nYour previous attempt was rejected:\n"
                + "\n".join(f"- {v}" for v in result.blocking)
                + "\nRewrite it without those claims."
            )

        submission.sections[section] = drafted

    combined = " ".join(d.text for d in submission.sections.values() if d.is_usable)
    if combined:
        from haru.validation.grounding import find_omissions

        submission.omissions = find_omissions(combined, repo)

    return submission
