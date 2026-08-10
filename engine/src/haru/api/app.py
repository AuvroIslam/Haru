"""The local control panel (PRD §16.1).

Runs on the user's machine and serves pages to their browser. Nothing leaves
the device: no account, no server, no telemetry. The desktop shell, when it
arrives, displays these same pages in a window.

Two constraints shape the code:

* **No build step.** Server-rendered HTML and one stylesheet. There is no
  bundler, no ``node_modules``, and the whole UI is readable by anyone who
  opens the templates — which matters for a tool that handles a passport
  number and asks to be trusted.
* **Webview-safe.** Nothing here assumes a URL bar, browser extensions, or
  APIs a plain webview lacks, so wrapping it in Electron later changes nothing.

The approval page is the important one. PRD §14.2 is explicit that a yes/no
dialog is not consent — the user sees every value that will be submitted, every
document, the fit reasoning, and everything Haru is unsure about, before
anything is typed into a form.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from haru.api.registry import (
    ApprovalExpired,
    ApprovalRegistry,
    Decision,
    NotSubmittable,
)
from haru.brain.review import ReviewQueue
from haru.brain.store import BrainStore
from haru.validation.seam import is_stubbed

HERE = Path(__file__).parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"


def create_app(
    store: BrainStore | None = None,
    registry: ApprovalRegistry | None = None,
) -> FastAPI:
    """Build the app. Dependencies are injected so tests need no globals."""
    app = FastAPI(title="Haru", docs_url=None, redoc_url=None)
    app.state.store = store
    # `registry or ApprovalRegistry()` would be wrong: ApprovalRegistry defines
    # __len__, so an empty one is falsy and the caller's registry would be
    # silently replaced — approvals would submit into an object nothing reads.
    app.state.registry = registry if registry is not None else ApprovalRegistry()

    templates = Jinja2Templates(directory=str(TEMPLATES))
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    def page(request: Request, name: str, **context) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name=name,
            context={"validation_stubbed": is_stubbed(), **context},
        )

    # ── queue ────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        registry: ApprovalRegistry = app.state.registry
        review = _review_count(app)
        return page(
            request,
            "index.html",
            pending=registry.pending(),
            decided=registry.decided()[:10],
            review_count=review,
        )

    # ── approval ─────────────────────────────────────────────────────────

    @app.get("/approve/{approval_id}", response_class=HTMLResponse)
    def show_approval(request: Request, approval_id: str) -> HTMLResponse:
        item = app.state.registry.get(approval_id)
        if item is None:
            return page(request, "missing.html", what="approval", status_code=404)
        return page(request, "approve.html", item=item, plan=item.plan)

    @app.post("/approve/{approval_id}")
    def decide(
        request: Request,
        approval_id: str,
        action: str = Form(...),
        note: str = Form(""),
    ):
        registry: ApprovalRegistry = app.state.registry
        item = registry.get(approval_id)
        if item is None:
            return page(request, "missing.html", what="approval", status_code=404)

        if action == "reject":
            registry.reject(approval_id, note=note)
            return RedirectResponse("/", status_code=303)

        try:
            registry.approve(approval_id, note=note)
        except NotSubmittable as exc:
            # Re-render rather than redirect so the reasons stay on screen.
            return page(
                request,
                "approve.html",
                item=item,
                plan=item.plan,
                error="Cannot approve yet — resolve these first:",
                error_details=exc.blockers,
            )
        except ApprovalExpired:
            return page(
                request,
                "approve.html",
                item=item,
                plan=item.plan,
                error="This request expired. Re-run the application to rebuild it.",
                error_details=[],
            )
        return RedirectResponse("/", status_code=303)

    # ── brain review ─────────────────────────────────────────────────────

    @app.get("/brain", response_class=HTMLResponse)
    def brain(request: Request) -> HTMLResponse:
        store: BrainStore | None = app.state.store
        if store is None:
            return page(request, "missing.html", what="Brain")
        queue = ReviewQueue(store)
        return page(request, "brain.html", items=queue.pending(), counts=store.counts())

    @app.post("/brain/{record_id}")
    def review_record(
        request: Request, record_id: str, action: str = Form(...)
    ):
        store: BrainStore | None = app.state.store
        if store is None:
            return page(request, "missing.html", what="Brain")
        queue = ReviewQueue(store)
        target = next(
            (i.record for i in queue.pending() if i.record.id == record_id), None
        )
        if target is not None:
            if action == "confirm":
                queue.confirm(target)
            elif action == "reject":
                queue.reject(target)
        return RedirectResponse("/brain", status_code=303)

    # ── json ─────────────────────────────────────────────────────────────

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "validation_stubbed": is_stubbed(),
            "pending_approvals": len(app.state.registry.pending()),
        }

    @app.get("/api/approvals/{approval_id}")
    def approval_json(approval_id: str) -> dict:
        item = app.state.registry.get(approval_id)
        if item is None:
            return {"error": "not found"}
        plan = item.plan
        return {
            "id": item.id,
            "status": item.status.value,
            "title": item.title,
            "fit": plan.fit.summary(),
            "submittable": plan.is_submittable,
            "blockers": plan.blockers(),
            "fill": [
                {"label": p.label, "value": p.match.value, "confidence": p.match.confidence}
                for p in plan.to_fill
            ],
            "ask": [{"label": p.label, "reason": p.reason} for p in plan.to_ask],
        }

    return app


def _review_count(app: FastAPI) -> int:
    store: BrainStore | None = app.state.store
    return ReviewQueue(store).count() if store is not None else 0


__all__ = ["create_app", "ApprovalRegistry", "Decision"]
