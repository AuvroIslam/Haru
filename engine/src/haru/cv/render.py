"""Rendering a tailored CV (PRD §11.3).

HTML/CSS is the rendering target: deterministic, inspectable, and tweakable by
users who know CSS. Every value that affects appearance comes from
:class:`~haru.cv.models.Style`, so two CVs built from the same template are
byte-identical in styling regardless of the content selected.

PDF output is a seam rather than an implementation: it needs headless Chrome,
which arrives with the browser layer in M2. :func:`render_pdf` raises clearly
until then rather than silently producing something else.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from haru.cv.models import RenderedSection, Slot, Style, TailoredCV


def style_css(style: Style) -> str:
    """Every appearance-affecting value, in one place."""
    return f"""
@page {{ margin: {style.page_margin_mm}mm; }}
* {{ box-sizing: border-box; }}
body {{
  font-family: {style.font_family};
  font-size: {style.body_size_pt}pt;
  line-height: {style.line_height};
  color: {style.text_color};
  margin: 0;
  padding: {style.page_margin_mm}mm;
}}
.name {{
  font-size: {style.name_size_pt}pt;
  color: {style.accent_color};
  margin: 0 0 2mm 0;
  letter-spacing: 0.01em;
}}
.contact {{
  color: {style.muted_color};
  margin-bottom: {style.section_gap_mm}mm;
}}
.contact span + span::before {{ content: " · "; }}
section {{ margin-bottom: {style.section_gap_mm}mm; }}
h2 {{
  font-size: {style.heading_size_pt}pt;
  color: {style.accent_color};
  text-transform: uppercase;
  letter-spacing: 0.08em;
  border-bottom: 0.4pt solid {style.accent_color};
  padding-bottom: 1mm;
  margin: 0 0 2mm 0;
}}
.item {{ margin-bottom: 3mm; }}
.item-head {{ display: flex; justify-content: space-between; gap: 4mm; }}
.item-title {{ font-weight: 700; }}
.item-sub {{ color: {style.muted_color}; }}
.item-detail {{ margin: 0.5mm 0; }}
ul {{ margin: 1mm 0 0 0; padding-left: 4mm; }}
li {{ margin-bottom: 0.5mm; }}
.skills {{ margin: 0; }}
""".strip()


def _render_items(section: RenderedSection) -> str:
    if section.slot is Slot.SKILLS:
        names = " · ".join(escape(i.title) for i in section.items)
        return f'<p class="skills">{names}</p>'

    blocks: list[str] = []
    for item in section.items:
        head = f'<span class="item-title">{escape(item.title)}</span>'
        if item.subtitle:
            head += f'<span class="item-sub">{escape(item.subtitle)}</span>'
        parts = [f'<div class="item-head">{head}</div>']
        if item.detail:
            parts.append(f'<div class="item-detail">{escape(item.detail)}</div>')
        if item.bullets:
            bullets = "".join(f"<li>{escape(b)}</li>" for b in item.bullets)
            parts.append(f"<ul>{bullets}</ul>")
        blocks.append(f'<div class="item">{"".join(parts)}</div>')
    return "".join(blocks)


def render_html(cv: TailoredCV, *, title: str | None = None) -> str:
    """Render to a standalone HTML document."""
    sections: list[str] = []
    for section in cv.sections:
        body = (
            f"<p>{escape(section.text)}</p>"
            if section.slot is Slot.SUMMARY and section.text
            else _render_items(section)
        )
        sections.append(
            f"<section><h2>{escape(section.heading)}</h2>{body}</section>"
        )

    contact = "".join(f"<span>{escape(line)}</span>" for line in cv.contact_lines)
    doc_title = escape(title or cv.display_name or "CV")

    return (
        "<!doctype html>\n"
        f'<html lang="en"><head><meta charset="utf-8">'
        f"<title>{doc_title}</title>"
        f"<style>{style_css(cv.style)}</style></head><body>"
        f'<h1 class="name">{escape(cv.display_name)}</h1>'
        f'<div class="contact">{contact}</div>'
        f'{"".join(sections)}'
        "</body></html>"
    )


def write_html(cv: TailoredCV, path: Path | str, *, title: str | None = None) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_html(cv, title=title), encoding="utf-8")
    return target


def render_pdf(cv: TailoredCV, path: Path | str, *, title: str | None = None) -> Path:
    """Print the CV to PDF through headless Chrome.

    Deliberately the *same* renderer as :func:`render_html` — the PDF is that
    HTML printed, not a second implementation. Two renderers means two
    appearances, and the user only ever approves one of them.

    Raises :class:`RuntimeError` rather than falling back to another engine if
    Chromium is unavailable, for the same reason.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on install
        raise RuntimeError(
            "PDF rendering needs Playwright. Install it, or use render_html()."
        ) from exc

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(cv, title=title)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(
                path=str(target),
                format="A4",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            browser.close()
    return target
