"""CV template and content models (PRD §11).

The one design decision everything else follows from: **presentation and content
never mix.** A template owns layout, fonts, spacing, section order and heading
labels. Content comes from the Brain, selected per target. Tailoring changes
only the content side, so output is pixel-stable across every application —
which is exactly what the brief asked for: *"cv style same, just projects in and
out and heading or whatever will be changed."*

``Style`` is deliberately inert here. Nothing in the tailoring path may write to
it; :func:`haru.cv.tailor.tailor` copies it through untouched and a test pins that.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from haru.brain.models import DEFAULT_PROFILE_ID, _new_id


class Slot(str, Enum):
    """A kind of content a section can hold."""

    SUMMARY = "summary"
    EXPERIENCE = "experience"
    PROJECTS = "projects"
    SKILLS = "skills"
    EDUCATION = "education"
    CREDENTIALS = "credentials"


class Style(BaseModel):
    """Pure presentation. Never modified by tailoring."""

    model_config = ConfigDict(frozen=True)

    font_family: str = "Georgia, 'Times New Roman', serif"
    body_size_pt: float = 10.5
    heading_size_pt: float = 12.5
    name_size_pt: float = 20.0
    line_height: float = 1.4
    accent_color: str = "#1a1a1a"
    text_color: str = "#222222"
    muted_color: str = "#666666"
    page_margin_mm: float = 16.0
    section_gap_mm: float = 5.0


class Section(BaseModel):
    """One block of the CV. ``heading`` is the user-visible label."""

    model_config = ConfigDict(validate_assignment=True)

    slot: Slot
    #: Renameable per target — "Projects" → "Selected Work" (PRD §11.2).
    heading: str
    max_items: int | None = None
    enabled: bool = True


def default_sections() -> list[Section]:
    return [
        Section(slot=Slot.SUMMARY, heading="Summary"),
        Section(slot=Slot.SKILLS, heading="Skills"),
        Section(slot=Slot.EXPERIENCE, heading="Experience", max_items=4),
        Section(slot=Slot.PROJECTS, heading="Projects", max_items=3),
        Section(slot=Slot.EDUCATION, heading="Education", max_items=2),
        Section(slot=Slot.CREDENTIALS, heading="Certifications"),
    ]


class CVTemplate(BaseModel):
    """The user's design. Owned by them, stable across applications."""

    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=_new_id)
    profile_id: str = DEFAULT_PROFILE_ID
    name: str = "Default"
    style: Style = Field(default_factory=Style)
    sections: list[Section] = Field(default_factory=default_sections)

    def section_for(self, slot: Slot) -> Section | None:
        return next((s for s in self.sections if s.slot is slot), None)

    @property
    def slot_order(self) -> list[Slot]:
        return [s.slot for s in self.sections if s.enabled]


class Ask(BaseModel):
    """What a target wants. Produced by an adapter; consumed by selection.

    Kept deliberately thin so the CV engine does not depend on any particular
    adapter — a job posting, a grant call and a hackathon track all reduce to
    "here are the things that matter".
    """

    model_config = ConfigDict(frozen=True)

    role: str | None = None
    org: str | None = None
    requirements: tuple[str, ...] = ()
    raw_text: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.requirements


class SelectedItem(BaseModel):
    """One chosen piece of content, with the reason it was chosen.

    The reason is not decoration: the review diff (PRD §11.4) shows it to the
    user so they can judge the selection rather than trusting it.
    """

    model_config = ConfigDict(frozen=True)

    record_id: str
    title: str
    subtitle: str | None = None
    detail: str | None = None
    bullets: tuple[str, ...] = ()
    score: float = 0.0
    matched: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        if not self.matched:
            return "included to fill the section"
        return "matches " + ", ".join(sorted(self.matched))


class RenderedSection(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot: Slot
    heading: str
    items: tuple[SelectedItem, ...] = ()
    text: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.items and not self.text


class TailoredCV(BaseModel):
    """A CV built for one target. Content varies; style does not."""

    model_config = ConfigDict(frozen=True)

    template_id: str
    profile_id: str = DEFAULT_PROFILE_ID
    display_name: str = ""
    contact_lines: tuple[str, ...] = ()
    style: Style = Field(default_factory=Style)
    sections: tuple[RenderedSection, ...] = ()
    ask: Ask | None = None

    def section_for(self, slot: Slot) -> RenderedSection | None:
        return next((s for s in self.sections if s.slot is slot), None)

    @property
    def item_ids(self) -> set[str]:
        return {i.record_id for s in self.sections for i in s.items}
