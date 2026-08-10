"""Content selection and tailoring (PRD §11.2).

Two rules govern everything here:

**Only confirmed facts are eligible.** Selection reads with
``confirmed_only=True``. An unreviewed import can sit in the Brain forever
without ever reaching a CV.

**Style is copied through, never computed.** Tailoring rewrites the content
side only. :func:`tailor` passes ``template.style`` through by reference.

Relevance scoring is deterministic term overlap, normalised the same way the
fact boundary normalises, so ``Node.js`` and ``nodejs`` match here exactly as
they do there. Embedding-based matching is a later upgrade behind the same
function signature — this is honest and free, and it makes the diff explainable,
which matters more early than raw ranking quality.
"""

from __future__ import annotations

from haru.brain.fact_boundary import normalize
from haru.brain.models import (
    DEFAULT_PROFILE_ID,
    Credential,
    Education,
    Experience,
    Identity,
    Project,
    Skill,
)
from haru.brain.store import BrainStore
from haru.cv.models import (
    Ask,
    CVTemplate,
    RenderedSection,
    SelectedItem,
    Slot,
    TailoredCV,
)
from haru.validation.seam import validate
from haru.validation.types import Artifact, ArtifactKind


def score(terms: list[str], ask: Ask) -> tuple[float, tuple[str, ...]]:
    """Fraction of the ask's requirements this item covers, plus which ones.

    Scoring by *coverage of the requirement* rather than count of matches stops
    an item with fifty listed technologies from dominating one with three
    relevant ones.
    """
    if ask.is_empty:
        return 0.0, ()
    have = {normalize(t) for t in terms if normalize(t)}
    matched = tuple(r for r in ask.requirements if normalize(r) in have)
    return len(matched) / len(ask.requirements), matched


def _truncate(items: list[SelectedItem], limit: int | None) -> tuple[SelectedItem, ...]:
    return tuple(items if limit is None else items[:limit])


def _rank(items: list[SelectedItem]) -> list[SelectedItem]:
    """Highest score first; ties keep their original (chronological) order."""
    return sorted(items, key=lambda i: -i.score)


def select_experiences(
    store: BrainStore, ask: Ask, *, profile_id: str = DEFAULT_PROFILE_ID
) -> list[SelectedItem]:
    items: list[SelectedItem] = []
    for exp in store.list(Experience, profile_id=profile_id, confirmed_only=True):
        terms = list(exp.skills) + list(exp.technologies)
        value, matched = score(terms, ask)
        bullets = tuple(a.text for a in exp.achievements)
        items.append(
            SelectedItem(
                record_id=exp.id,
                title=exp.title,
                subtitle=exp.org,
                detail=exp.summary,
                bullets=bullets,
                score=value,
                matched=matched,
            )
        )
    return _rank(items)


def select_projects(
    store: BrainStore, ask: Ask, *, profile_id: str = DEFAULT_PROFILE_ID
) -> list[SelectedItem]:
    items: list[SelectedItem] = []
    for proj in store.list(Project, profile_id=profile_id, confirmed_only=True):
        terms = list(proj.technologies) + list(proj.skills_demonstrated)
        value, matched = score(terms, ask)
        items.append(
            SelectedItem(
                record_id=proj.id,
                title=proj.name,
                subtitle=proj.tagline,
                detail=proj.description,
                bullets=tuple(o.text for o in proj.outcomes),
                score=value,
                matched=matched,
            )
        )
    return _rank(items)


def select_skills(
    store: BrainStore, ask: Ask, *, profile_id: str = DEFAULT_PROFILE_ID
) -> list[SelectedItem]:
    """Skills the user actually has, relevant ones first.

    Only skills with evidence appear — the same bar the fact boundary applies.
    """
    items: list[SelectedItem] = []
    wanted = {normalize(r) for r in ask.requirements}
    for skill in store.list(Skill, profile_id=profile_id, confirmed_only=True):
        if not skill.has_evidence:
            continue
        hit = normalize(skill.name) in wanted
        items.append(
            SelectedItem(
                record_id=skill.id,
                title=skill.name,
                subtitle=skill.category,
                score=1.0 if hit else 0.0,
                matched=(skill.name,) if hit else (),
            )
        )
    return _rank(items)


def select_education(
    store: BrainStore, *, profile_id: str = DEFAULT_PROFILE_ID
) -> list[SelectedItem]:
    return [
        SelectedItem(
            record_id=e.id,
            title=e.degree or "Studied",
            subtitle=e.institution,
            detail=e.field_of_study,
        )
        for e in store.list(Education, profile_id=profile_id, confirmed_only=True)
    ]


def select_credentials(
    store: BrainStore, *, profile_id: str = DEFAULT_PROFILE_ID
) -> list[SelectedItem]:
    """Only credentials that are claimable — confirmed *and* evidenced.

    PRD §10.2: certifications are never stretchable. A credential without a
    supporting document never reaches a CV, regardless of confirmation.
    """
    return [
        SelectedItem(record_id=c.id, title=c.name, subtitle=c.issuer)
        for c in store.list(Credential, profile_id=profile_id, confirmed_only=True)
        if c.is_claimable and not c.is_expired()
    ]


def build_summary(
    store: BrainStore,
    ask: Ask,
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
) -> str | None:
    """Compose a summary from confirmed facts only.

    Deterministic and fact-derived — no model involved yet. It still goes
    through the validation seam so the observation log captures real generation
    during M1–M2 (PRD §17.1).
    """
    experiences = store.list(Experience, profile_id=profile_id, confirmed_only=True)
    skills = [
        s
        for s in store.list(Skill, profile_id=profile_id, confirmed_only=True)
        if s.has_evidence
    ]
    if not experiences and not skills:
        return None

    parts: list[str] = []
    if experiences:
        latest = experiences[0]
        parts.append(f"{latest.title} at {latest.org}")
    if skills:
        relevant = [s.name for s in select_relevant_skill_names(skills, ask)][:5]
        if relevant:
            parts.append("works with " + ", ".join(relevant))

    text = ". ".join(parts) + "." if parts else None
    if text:
        validate(
            Artifact(
                kind=ArtifactKind.CV_SUMMARY,
                text=text,
                profile_id=profile_id,
                context={"role": ask.role or "", "org": ask.org or ""},
            ),
            _boundary_for(store, profile_id),
        )
    return text


def select_relevant_skill_names(skills: list[Skill], ask: Ask) -> list[Skill]:
    wanted = {normalize(r) for r in ask.requirements}
    return sorted(skills, key=lambda s: normalize(s.name) not in wanted)


def _boundary_for(store: BrainStore, profile_id: str):
    from haru.brain.fact_boundary import derive

    return derive(store, profile_id=profile_id)


def _contact_lines(identity: Identity | None) -> tuple[str, ...]:
    if identity is None:
        return ()
    lines: list[str] = []
    if identity.emails:
        lines.append(identity.emails[0].value)
    if identity.phones:
        lines.append(identity.phones[0].value)
    where = [f.value for f in (identity.city, identity.country) if f is not None]
    if where:
        lines.append(", ".join(where))
    lines.extend(link.url for link in identity.links)
    return tuple(lines)


def tailor(
    store: BrainStore,
    template: CVTemplate,
    ask: Ask | None = None,
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
) -> TailoredCV:
    """Build a CV for one target.

    Section order, headings and style come from the template untouched. Only
    which items appear, and in what order, responds to the ask.
    """
    ask = ask or Ask()
    identity = store.get_singleton(Identity, profile_id=profile_id)

    pools = {
        Slot.EXPERIENCE: lambda: select_experiences(store, ask, profile_id=profile_id),
        Slot.PROJECTS: lambda: select_projects(store, ask, profile_id=profile_id),
        Slot.SKILLS: lambda: select_skills(store, ask, profile_id=profile_id),
        Slot.EDUCATION: lambda: select_education(store, profile_id=profile_id),
        Slot.CREDENTIALS: lambda: select_credentials(store, profile_id=profile_id),
    }

    sections: list[RenderedSection] = []
    for section in template.sections:
        if not section.enabled:
            continue
        if section.slot is Slot.SUMMARY:
            text = build_summary(store, ask, profile_id=profile_id)
            rendered = RenderedSection(
                slot=section.slot, heading=section.heading, text=text
            )
        else:
            items = _truncate(pools[section.slot](), section.max_items)
            rendered = RenderedSection(
                slot=section.slot, heading=section.heading, items=items
            )
        if not rendered.is_empty:
            sections.append(rendered)

    name = ""
    if identity is not None:
        chosen = identity.preferred_name or identity.legal_name
        name = chosen.value if chosen else ""

    return TailoredCV(
        template_id=template.id,
        profile_id=profile_id,
        display_name=name,
        contact_lines=_contact_lines(identity),
        style=template.style,
        sections=tuple(sections),
        ask=ask,
    )
