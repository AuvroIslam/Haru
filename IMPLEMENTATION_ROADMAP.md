# Haru — Technical Build Plan

**Companion to:** [PRD.md](PRD.md) (Draft 2.0)
**Status:** Draft 2.0 — rewritten for the identity-layer product
**Last updated:** 2026-08-10

> Nothing here has been built or measured. Every number is a target or an estimate, and every
> version is unpinned until checked against a registry.

---

## 1. Architecture decisions

### 1.1 Language split — **decided: Python core, TypeScript surfaces**

| Layer | Language | Why |
| --- | --- | --- |
| Core engine, Brain, validators, adapters | Python | Document parsing, local model runtimes, embeddings, and PDF tooling are all strongest here |
| Browser extension | TypeScript | No choice |
| Desktop shell | TypeScript (Tauri or Electron) | Wraps the Python engine |
| Local dashboard | TypeScript | Shares components with the extension |

The engine is a **local HTTP + WebSocket service**. Every surface talks to it the same way. This
keeps the extension, desktop app, and chat bot from each reimplementing logic.

### 1.2 Storage — **decided: SQLite + encrypted file vault**

- SQLite for the Brain, tracker, adapters, question bank. Single file, portable, greppable.
- Documents encrypted at rest in a vault directory, keyed from an OS-keychain-held key.
- Embeddings in the same SQLite file via `sqlite-vec` (avoid a second datastore until proven necessary).
- **Export to plain JSON + files must work from M0.** P2 in the PRD means no lock-in, and that's
  easy to build in and painful to retrofit.

### 1.3 Browser control — **decided: user's own browser via CDP**

Attach to the user's real Chrome profile rather than launching a clean automation browser.
Follows PRD P7 and §12.7: existing session, no stored passwords, no login automation.

- **Playwright** for control (mature, typed, good CDP access)
- **Browser Use** consulted for its watchdog/recovery patterns; adopt the pattern, depend on the
  library only where it earns its place
- Extension provides in-page capabilities CDP can't reach cleanly (capture button, side panel, overlay)

### 1.4 Execution model

```
Goal
 └→ Adapter available? ──yes→ Deterministic replay (T0, zero tokens)
                        │         └ step fails → agent for that step → heal adapter
                        └──no──→ Agent loop, recording as it goes → new adapter
```

Agent loop is strictly: **scan → one action → verify → rescan → repeat.** No multi-step plans.

### 1.5 Model runtime — **decided: Ollama for local, provider-agnostic interface**

Ollama for T1/T2 (easy install, good model coverage), behind an interface thin enough to swap for
llama.cpp later. Cloud providers behind the same interface, opt-in only. Embeddings always local.

---

## 2. Repository layout

```
haru/
├── engine/                          # Python — the product
│   ├── haru/
│   │   ├── brain/                   # M0
│   │   │   ├── models.py            # Pydantic schema (PRD §6.2)
│   │   │   ├── store.py             # SQLite persistence
│   │   │   ├── provenance.py        # source + confidence + confirmation
│   │   │   ├── review_queue.py      # nothing enters confirmed unreviewed
│   │   │   └── importers/
│   │   │       ├── cv.py            # PDF/DOCX → facts
│   │   │       ├── github.py
│   │   │       ├── devpost.py
│   │   │       └── linkedin_export.py
│   │   ├── vault/                   # M0 — encrypted documents, expiry
│   │   ├── validation/              # M1 — BUILD BEFORE ANY GENERATION
│   │   │   ├── fact_boundary.py
│   │   │   ├── cliche.py
│   │   │   ├── leakage.py
│   │   │   └── repo_grounding.py    # M6 — claims vs actual code
│   │   ├── cv/                      # M2
│   │   │   ├── template.py          # layout, slots, headings
│   │   │   ├── content.py           # selection + ordering
│   │   │   ├── tailor.py
│   │   │   ├── render.py            # HTML/CSS → PDF; LaTeX path
│   │   │   └── diff.py              # reviewable change list
│   │   ├── execution/               # M3
│   │   │   ├── registry.py          # typed actions
│   │   │   ├── loop.py              # one action per turn
│   │   │   ├── verify.py            # post-action verification (P4)
│   │   │   ├── dom.py               # scan, stable ids, native setter
│   │   │   ├── vision.py            # fallback
│   │   │   ├── guard.py             # loop detection, step cap, kill switch
│   │   │   └── session.py           # state across navigation
│   │   ├── adapters/
│   │   │   ├── base.py              # Ask extraction → fill → verify contract
│   │   │   ├── job/                 # M4
│   │   │   ├── hackathon/           # M6
│   │   │   ├── government/          # M8
│   │   │   ├── generic/             # M12
│   │   │   └── sites/               # M9 — recorded deterministic workflows
│   │   ├── discovery/               # M7 — inbox, classify, enrich, score, dedup
│   │   ├── models/                  # M5 — router, tiers, cost meter, redaction
│   │   ├── tracker/                 # M10
│   │   ├── evidence/                # audit records
│   │   └── api/                     # HTTP + WebSocket
│   └── tests/
├── extension/                       # TypeScript
├── desktop/                         # Tauri/Electron shell
├── dashboard/                       # local web UI
├── PRD.md
├── IMPLEMENTATION_ROADMAP.md
└── RelatedIdeas.md
```

---

## 3. Milestone detail

### M0 — Brain core

**Done when:** import a CV, review what was extracted, and have a confirmed record with provenance.

- Pydantic models for the full PRD §6.2 schema
- SQLite store with migrations
- Every fact carries `source`, `confidence`, `confirmed`, `confirmed_at`
- Review queue — imports land unconfirmed
- CV parsing (PDF + DOCX)
- Encrypted vault with expiry tracking
- JSON export

**Watch for:** CV parsing quality varies wildly. Don't chase perfect extraction — the review
queue is the safety net. Ship "reviewable" before "accurate."

### M1 — Fact boundary *(before any generation exists)*

**Done when:** text claiming an unowned skill is reliably blocked, proven by adversarial tests.

- `allowed_skills` derived from `skills[]` + evidence links
- Blocking check against orgs, projects, institutions, metrics
- **Credentials: exact match against `credentials[]` with a document, no fuzzy allowance**
- Cliché list (seed from ApplyPilot's, extend)
- Leakage phrases — always blocking
- Modes: strict / normal / lenient — the fact-boundary check is **not** relaxable in any mode
- Regenerate-with-feedback loop, capped, then escalate to the user

**Test approach:** a corpus of deliberate fabrications — invented certs, inflated metrics,
plausible-but-unowned frameworks, fabricated employers. Aim for zero escapes on the blocking
checks. This is the test suite that matters most in the whole product.

### M2 — CV engine

**Done when:** two different jobs produce two different CVs with byte-identical styling.

- Template model: layout, slots, section order, heading labels
- Three import paths (auto-extract / bring-your-own / starter)
- Content selection driven by semantic match against the Ask
- Renderer: HTML/CSS → PDF via headless Chrome; LaTeX path for existing LaTeX users
- Diff view with per-change attribution and individual veto
- Multiple named templates

**Watch for:** scope creep into a CV builder. Haru selects and arranges; it is not a design tool.

### M3 — Execution core

**Done when:** a React-based ATS form is filled with every field verified.

- Typed action registry with declared preconditions and verification
- One-action-per-turn loop
- Post-action verification for every action type (PRD §12.3)
- Native value setter + `input`/`change` events (PRD §12.4) — **write this test first, against a
  real React form**
- Stable element IDs; loop guard with nudge-before-abort
- Step cap, kill switch
- State persistence across navigation
- DOM → vision fallback

**Watch for:** this is where the hard bugs live. Budget more than feels reasonable.

### M4 — Job adapter

First real end-to-end. Greenhouse and Lever first (cleanest, both React), Workday later (hardest).

Extraction → matching → generation (gated by M1) → approval preview → submit → evidence.

### M5 — Local model router

**Done when:** a complete application runs with no API key at zero cost.

Hardware probe, T0–T2 local, T3 opt-in, cost meter, redaction layer, cloud-call log.
Enforce: raw PII never leaves the device; high-stakes mode blocks T3.

### M6 — Hackathon adapter

Repo ingestion (README, languages, commits, structure), Devpost field extraction, story
generation, and **repo-grounded validation** — claims checked against actual code, plus flagging
real work the draft omitted.

### M7 — Opportunity Inbox

Capture button, forward-in, classification, three-tier enrichment (JSON-LD → selectors → model),
scoring, dedup, deadline extraction. **No auto-submit from discovery, ever.**

### M8 — Government adapter

High-stakes mode: 0.95 confidence threshold, field-by-field review, no cloud models, minimal
prose, full audit record. Document extraction for ID/passport/transcripts.

### M9 — Deterministic adapters

Recording, replay, healing. Target: tenth application to a known ATS uses zero tokens.

### M10–M12

Tracker with honest sample-size reporting · chat surface · generic form fallback.

---

## 4. Test strategy

| Layer | Approach |
| --- | --- |
| **Fact boundary** | Adversarial corpus. Highest-priority suite in the codebase. |
| **Execution** | Fixture pages reproducing real ATS behavior — React controlled inputs, custom dropdowns, multi-page flows, file uploads |
| **Adapters** | Recorded HTTP + saved DOM snapshots; no live sites in CI |
| **CV render** | Golden-file PDF comparison to catch styling drift |
| **End-to-end** | Manual, against real sites, using dry-run mode. Never in CI. |

**Dry-run mode is a first-class feature, not a test flag** — fill everything, submit nothing.

---

## 5. Per-milestone definition of done

Applies to every milestone, per [CLAUDE.md](CLAUDE.md):

1. Feature implemented
2. Tests written and passing
3. Committed and pushed (5–6 word message, no Claude attribution)

A milestone is not done until something demonstrably works end-to-end. No milestone lands as
scaffolding only.

---

## 6. Immediate next steps

1. Decide the open questions in PRD §20 that block M0 — specifically license and whether the
   Brain is single or multi-profile (it changes the schema).
2. Scaffold `engine/` and get the API skeleton running.
3. Write the Brain schema from PRD §6.2.
4. Build the adversarial fabrication corpus **before** the validator, so M1 has a real target.

---

## 7. Deferred decisions

Not blocking, but don't let them ambush us later:

- Sync/backup across the user's own machines (must preserve P2 — user owns the data)
- Sharing site adapters between users (trust and review model)
- Whether the desktop shell is Tauri or Electron (decide at M3, when the engine's real needs are known)
- Packaging and distribution
