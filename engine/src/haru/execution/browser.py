"""Playwright executor — the real browser (PRD §12.4, §12.7).

Runs in the user's own browser session. No password storage, no login
automation: Haru does what the user asked, in the session they already have.

The important part of this file is :data:`NATIVE_SETTER_JS`. Assigning to
``element.value`` on a React-controlled input updates the DOM but does not fire
React's synthetic ``onChange``, so the component's state never learns about the
text. The field *looks* filled and submits empty. Greenhouse, Lever and Ashby
are all React, so this is the common case, not an edge case.

The fix goes through the prototype's native setter, which React's value tracker
observes, then dispatches the events React listens for.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from haru.execution.actions import Action, ActionType
from haru.execution.executor import ExecutionError, TargetNotFound
from haru.execution.page import Element, ElementRole, PageSnapshot

log = logging.getLogger(__name__)

#: Writes a value the way a user would, so framework value-trackers notice.
NATIVE_SETTER_JS = """
(el, value) => {
  const proto = el instanceof window.HTMLTextAreaElement
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, value);
  el.dispatchEvent(new Event('input',  { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return el.value;
}
"""

#: Collects interactive elements and assigns the indices the decider uses.
SCAN_JS = r"""
() => {
  const SELECTOR = [
    'input:not([type=hidden])', 'textarea', 'select', 'button',
    'a[href]', '[role=button]', '[role=checkbox]', '[role=radio]',
    '[contenteditable=true]'
  ].join(',');

  const roleOf = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'textarea') return 'textarea';
    if (tag === 'select') return 'select';
    if (tag === 'button') return 'button';
    if (tag === 'a') return 'link';
    if (tag === 'input') {
      const t = (el.type || 'text').toLowerCase();
      if (t === 'checkbox') return 'checkbox';
      if (t === 'radio') return 'radio';
      if (t === 'file') return 'file';
      if (t === 'submit' || t === 'button') return 'button';
      return 'textbox';
    }
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (role === 'button' || role === 'checkbox' || role === 'radio') return role;
    return 'other';
  };

  const labelOf = (el) => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const src = document.getElementById(labelledBy);
      if (src) return (src.innerText || '').trim();
    }
    if (el.id) {
      // A <label for> names the control; we never treat the label itself as
      // the target, which would shadow the real element.
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) return (lab.innerText || '').trim();
    }
    const wrapping = el.closest('label');
    if (wrapping) return (wrapping.innerText || '').trim();
    if (el.placeholder) return el.placeholder.trim();
    if (el.name) return el.name.trim();
    return (el.innerText || el.value || '').trim().slice(0, 80);
  };

  const selectorOf = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    if (el.name) return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
    const parent = el.parentElement;
    if (!parent) return el.tagName.toLowerCase();
    const sameTag = Array.from(parent.children).filter(c => c.tagName === el.tagName);
    const nth = sameTag.indexOf(el) + 1;
    return `${el.tagName.toLowerCase()}:nth-of-type(${nth})`;
  };

  const results = [];
  let index = 0;
  for (const el of document.querySelectorAll(SELECTOR)) {
    const style = window.getComputedStyle(el);
    // display:none and visibility:hidden are genuinely not there. Zero size is
    // NOT a disqualifier — invisible overlays are real click targets.
    if (style.display === 'none' || style.visibility === 'hidden') continue;

    const box = el.getBoundingClientRect();
    const role = roleOf(el);
    results.push({
      index: index++,
      role,
      label: labelOf(el),
      value: (role === 'checkbox' || role === 'radio')
        ? (el.checked ? 'true' : '')
        : (el.value ?? ''),
      selector: selectorOf(el),
      tag: el.tagName.toLowerCase(),
      required: !!el.required,
      disabled: !!el.disabled,
      options: el.tagName.toLowerCase() === 'select'
        ? Array.from(el.options).map(o => o.value)
        : [],
      width: box.width,
      height: box.height
    });
  }
  return { url: location.href, title: document.title, elements: results,
           text: (document.body ? document.body.innerText : '').slice(0, 20000) };
}
"""


class PlaywrightExecutor:
    """Drives a real page. Satisfies :class:`~haru.execution.executor.Executor`."""

    def __init__(self, page: Any) -> None:
        self.page = page
        self._last: PageSnapshot | None = None

    # ── protocol ─────────────────────────────────────────────────────────

    def snapshot(self) -> PageSnapshot:
        raw = self.page.evaluate(SCAN_JS)
        elements = tuple(
            Element(
                index=e["index"],
                role=_role(e["role"]),
                label=e["label"],
                value=e["value"] or None,
                selector=e["selector"],
                tag=e["tag"],
                required=e["required"],
                disabled=e["disabled"],
                options=tuple(e["options"]),
                width=e["width"],
                height=e["height"],
            )
            for e in raw["elements"]
        )
        self._last = PageSnapshot(
            url=raw["url"],
            title=raw["title"],
            elements=elements,
            text=raw["text"],
        )
        return self._last

    def perform(self, action: Action, element: Element | None) -> None:
        kind = action.action_type

        if kind is ActionType.NAVIGATE:
            self.page.goto(action.url)
            return
        if kind is ActionType.SCROLL:
            self.page.mouse.wheel(0, int(action.value or 600))
            return
        if kind is ActionType.WAIT:
            self.page.wait_for_timeout(int(action.value or 500))
            return
        if kind in (ActionType.EXTRACT, ActionType.DONE):
            return
        if kind is ActionType.SCREENSHOT:
            if action.value:
                Path(action.value).parent.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=action.value)
            else:
                self.page.screenshot()
            return

        if element is None:
            raise TargetNotFound(f"{kind.value} needs a target element")

        handle = self._locate(element)

        if kind is ActionType.FILL:
            self._fill(handle, element, action.value or "")
        elif kind is ActionType.SELECT:
            handle.select_option(action.value)
        elif kind is ActionType.CHECK:
            want = (action.value or "true").lower() not in ("", "false")
            handle.set_checked(want)
        elif kind is ActionType.UPLOAD:
            handle.set_input_files(action.value)
        elif kind in (ActionType.CLICK, ActionType.SUBMIT):
            handle.click()
            self._settle()
        else:  # pragma: no cover - every ActionType is handled above
            raise ExecutionError(f"unsupported action {kind.value}")

    # ── internals ────────────────────────────────────────────────────────

    def _locate(self, element: Element):
        try:
            locator = self.page.locator(element.selector).first
            locator.wait_for(state="attached", timeout=5000)
            return locator
        except Exception as exc:  # noqa: BLE001 - Playwright raises many types
            raise TargetNotFound(
                f"could not resolve {element.selector!r} for [{element.index}] "
                f"{element.label!r}"
            ) from exc

    def _fill(self, handle: Any, element: Element, value: str) -> None:
        """Write text so framework-controlled components actually see it."""
        if element.needs_native_setter:
            handle.evaluate(NATIVE_SETTER_JS, value)
            return
        handle.fill(value)

    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:  # noqa: BLE001 - a busy page is not an error
            pass


def _role(name: str) -> ElementRole:
    try:
        return ElementRole(name)
    except ValueError:
        return ElementRole.OTHER
