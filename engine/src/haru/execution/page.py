"""Page representation handed to the decider (PRD §12.2).

The model never sees raw HTML and never writes a selector. It sees a numbered
list of interactive elements and refers to them by index.

That indirection is the single most valuable idea in Browser Use's DOM layer:
a model asked for a CSS selector will confidently invent one that matches
nothing, and the failure is silent. An index either resolves to an element we
found or it does not, and "it does not" is catchable.

Indices are per-snapshot. ``stable_key`` is what survives rescans and is what
the loop guard keys on, because a re-render can renumber everything without
changing what is actually on the page.
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ElementRole(str, Enum):
    BUTTON = "button"
    LINK = "link"
    TEXTBOX = "textbox"
    TEXTAREA = "textarea"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    FILE = "file"
    OTHER = "other"


#: Roles that hold a value we can read back after writing (PRD §12.3).
VALUED_ROLES: frozenset[ElementRole] = frozenset(
    {
        ElementRole.TEXTBOX,
        ElementRole.TEXTAREA,
        ElementRole.SELECT,
        ElementRole.CHECKBOX,
        ElementRole.RADIO,
    }
)

#: Roles whose value is written through the framework-safe setter (PRD §12.4).
NATIVE_SETTER_ROLES: frozenset[ElementRole] = frozenset(
    {ElementRole.TEXTBOX, ElementRole.TEXTAREA}
)


class Element(BaseModel):
    """One interactive thing on the page."""

    model_config = ConfigDict(frozen=True)

    index: int
    role: ElementRole
    label: str = ""
    value: str | None = None
    selector: str = ""
    tag: str = ""
    required: bool = False
    disabled: bool = False
    #: Options for selects and radio groups.
    options: tuple[str, ...] = ()
    #: Zero-size elements can still be real click targets (invisible overlays),
    #: so this is recorded but never used alone to decide interactivity.
    width: float = 0.0
    height: float = 0.0

    @property
    def stable_key(self) -> str:
        """Identity that survives a rescan.

        Built from what the page means rather than where it currently sits:
        indices renumber on re-render, and positions move on scroll.
        """
        basis = f"{self.tag}|{self.role.value}|{self.label}|{self.selector}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

    @property
    def holds_value(self) -> bool:
        return self.role in VALUED_ROLES

    @property
    def needs_native_setter(self) -> bool:
        return self.role in NATIVE_SETTER_ROLES

    def describe(self) -> str:
        bits = [f"[{self.index}]", self.role.value]
        if self.label:
            bits.append(repr(self.label))
        if self.required:
            bits.append("(required)")
        if self.disabled:
            bits.append("(disabled)")
        if self.value:
            bits.append(f"= {self.value!r}")
        return " ".join(bits)


class PageSnapshot(BaseModel):
    """What the page looked like at one moment."""

    model_config = ConfigDict(frozen=True)

    url: str
    title: str = ""
    elements: tuple[Element, ...] = ()
    text: str = ""

    def by_index(self, index: int) -> Element | None:
        return next((e for e in self.elements if e.index == index), None)

    def by_key(self, stable_key: str) -> Element | None:
        return next((e for e in self.elements if e.stable_key == stable_key), None)

    def by_label(self, label: str) -> Element | None:
        wanted = label.strip().lower()
        return next(
            (e for e in self.elements if e.label.strip().lower() == wanted), None
        )

    @property
    def required_fields(self) -> tuple[Element, ...]:
        return tuple(e for e in self.elements if e.required and e.holds_value)

    @property
    def unfilled_required(self) -> tuple[Element, ...]:
        return tuple(e for e in self.required_fields if not e.value)

    def describe(self, limit: int | None = None) -> str:
        """Compact listing for the decider."""
        shown = self.elements if limit is None else self.elements[:limit]
        lines = [f"{self.title or 'Untitled'} — {self.url}"]
        lines.extend(e.describe() for e in shown)
        if limit is not None and len(self.elements) > limit:
            lines.append(f"… {len(self.elements) - limit} more")
        return "\n".join(lines)

    def digest(self) -> str:
        """Fingerprint of the page's meaningful state.

        Used to tell "the click did something" from "the click did nothing",
        which is the cheapest post-action verification available (PRD §12.3).
        """
        parts = [self.url, self.title]
        parts.extend(f"{e.stable_key}={e.value or ''}" for e in self.elements)
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
