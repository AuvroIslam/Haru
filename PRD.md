# Haru — Product Requirements Document

**Status:** Draft 2.0 — full rewrite
**Supersedes:** Draft 1.0 (job-application agent, scoped for a hackathon)
**Last updated:** 2026-08-10

---

## 1. What Haru is

> **Haru holds your facts and your documents, and represents you on any form on the web.**

Not a job-application bot. Not a browser agent. The product is the **identity layer** — a
private, structured, verified record of who you are and what you've done — and a set of
adapters that carry it onto whatever the web asks you to fill in.

Job applications are the wedge because the pain is sharpest there. But a hackathon submission,
a passport renewal, a university application, a visa form, a grant proposal, and a rental
application are all the same shape underneath:

```
Something asks you for facts about yourself, plus prose about yourself,
in its own idiosyncratic format, with a deadline.
```

You have answered those questions a hundred times. Haru answers them for you, from a record
you own, without inventing anything, and shows you everything before it commits.

### The thesis

> You should type your own facts once, not once per form.
> And nothing should ever be submitted in your name that you haven't seen and that isn't true.

---

## 2. Honest competitive position

This section exists because the first draft of this PRD claimed novelty it didn't have.

### What already exists and works

| Project | What it covers | License |
| --- | --- | --- |
| [ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot) | Full job pipeline: discover → score → tailor → cover → auto-submit. 5 boards + 48 Workday portals. Production-grade. | AGPL-3.0 |
| [AIHawk](https://github.com/feder-cr/jobs_applier_ai_agent_aihawk) | LinkedIn Easy Apply mass-apply. Now largely abandoned by its author. | MIT |
| [Browser Use](https://github.com/browser-use/browser-use) | The browser automation substrate. ~93K stars. | MIT |
| [workflow-use](https://github.com/browser-use/workflow-use) | Deterministic recorded workflows with LLM fallback + healing. | MIT |
| [Cognito](https://gitlab.com/codewarnab-group/cognito-ai) | Chrome side-panel agent, local AI, MCP, action registry. | BUSL-1.1 — **source-available, not open source. Read only; do not copy code.** |
| [NaviNate](https://github.com/katiehclau-art/NaviNate) | Site-side embedded concierge. Company installs it for its own visitors. | Hackathon project |

**If we build "an AI agent that applies to jobs," we lose to ApplyPilot.** It is further along
than we would be, and it is free. That is settled.

### Where the room actually is

Every project above treats the user profile as a *config file for one vertical*. ApplyPilot's
is literally `profile.example.json`, scoped to job applications. Nobody has built the profile
as the product.

Haru's defensible ground, in order of strength:

1. **Cross-domain identity.** One brain that fills a job application, a Devpost submission, and
   a passport form. No competitor spans these.
2. **A site-adapter library that compounds.** Recorded, self-healing workflows per target site.
   Every failure permanently improves the system; every new adapter is a moat brick.
3. **Verified-honest output.** Generation is bounded by facts the user has confirmed. Nothing is
   invented. This is a *product* feature, not a compliance checkbox — see §3 and §10.
4. **Local-first economics.** Free to run by default. Paid models are an opt-in upgrade, not a
   dependency.
5. **The outcome loop.** Which CV version got interviews. Nobody closes this.

### What we are explicitly not competing on

**Volume.** AIHawk drew sustained press criticism (TechCrunch, Wired, The Verge, 404 Media —
*"AI is enabling job seekers to think like spammers"*; one reporter auto-applied to 2,843
roles). ApplyPilot leads with "1,000 jobs in 2 days." That framing invites the same backlash
and degrades the thing users actually want, which is to get hired. Haru optimizes quality per
submission and treats rate limiting as a feature.

---

## 3. Principles

These are non-negotiable and every design decision below traces back to one.

**P1 — Never fabricate.** Haru may reorganize, re-emphasize, and rephrase facts the user has
confirmed. It may never invent a skill, a metric, a date, a company, or a credential. Claiming
a certification you don't hold is fraud, and Haru will not do it on your behalf even if asked.

**P2 — The user owns the record.** The Personal Brain lives on the user's machine, in a format
they can read and export. No lock-in. No silent cloud sync.

**P3 — Show, then commit.** Nothing irreversible happens without the user seeing exactly what
will be submitted. Approval gates are not optional for submit/send/pay/delete.

**P4 — Verify, don't assume.** After every action, confirm the observable result before
reporting success. NaviNate shipped without this and named it their top regret; we build it in
from the start.

**P5 — Deterministic first, model second.** If a recorded workflow can do it, don't spend a
token. Models are for the unknown, not the routine.

**P6 — Free by default.** The product must be fully usable with local models and no API key.

**P7 — Work in the open, at human pace.** Haru operates in the user's own browser, in their own
already-authenticated session. It does not store passwords, does not automate login, and does
not enter a detection-evasion arms race. Where a site's terms forbid automation, the user is
told plainly and decides — see §16.2.

---

## 4. Users

### Primary — the serial applicant
Applies to many things across many systems: jobs, hackathons, grants, programs. Pain is
repetition and context-switching, not any single form.

### Secondary — the document-burdened
Immigrants, students, anyone dealing with government and institutional bureaucracy. Same forty
facts, twenty forms, each with its own vocabulary and its own uploaded-document requirements.
Stakes are higher and errors are costly.

### Tertiary — the builder
Ships projects, enters hackathons, maintains a portfolio. Needs their work described accurately
and repeatedly, tuned to each audience.

All three share one property: **they retype the same truths forever.**

---

## 5. The unified pipeline

Every target type runs the same eight stages. Adapters differ; the pipeline does not.

```
 ┌─ 1. CAPTURE ────────────────────────────────────────────┐
 │  A target enters the system (URL, forward, file, search) │
 └────────────────────────┬────────────────────────────────┘
                          ↓
 ┌─ 2. UNDERSTAND ─────────────────────────────────────────┐
 │  Classify target type. Extract its requirements into a   │
 │  structured Ask: fields, questions, documents, deadline. │
 └────────────────────────┬────────────────────────────────┘
                          ↓
 ┌─ 3. MATCH ──────────────────────────────────────────────┐
 │  Retrieve relevant facts, documents, and past answers    │
 │  from the Brain. Score fit. Flag what's missing.         │
 └────────────────────────┬────────────────────────────────┘
                          ↓
 ┌─ 4. ASK ────────────────────────────────────────────────┐
 │  Ask the user ONLY for what the Brain genuinely lacks.   │
 │  Every answer is written back to the Brain.              │
 └────────────────────────┬────────────────────────────────┘
                          ↓
 ┌─ 5. COMPOSE ────────────────────────────────────────────┐
 │  Generate documents and prose, bounded by the Fact       │
 │  Boundary. Render CV/letters in the user's own template. │
 └────────────────────────┬────────────────────────────────┘
                          ↓
 ┌─ 6. VALIDATE ───────────────────────────────────────────┐
 │  Fact-boundary check, quality check, completeness check. │
 │  Regenerate on failure; escalate if it keeps failing.    │
 └────────────────────────┬────────────────────────────────┘
                          ↓
 ┌─ 7. EXECUTE ────────────────────────────────────────────┐
 │  Deterministic replay if we have an adapter, else agent. │
 │  One action, verify it landed, rescan, repeat.           │
 └────────────────────────┬────────────────────────────────┘
                          ↓
 ┌─ 8. APPROVE → SUBMIT → RECORD ──────────────────────────┐
 │  Full preview. User approves. Submit. Capture evidence.  │
 │  Track outcome. Heal the adapter from what we learned.   │
 └─────────────────────────────────────────────────────────┘
```

**Why this matters:** requirements 1–4 from the brief (job discovery, CV tailoring, hackathon
submission, government forms) are not four features. They are four **adapters** over one
pipeline. That is the whole architectural bet.

---

## 6. The Personal Brain

The core asset. Everything else is an adapter over this.

### 6.1 Design rules

- **Every fact carries provenance.** Where it came from (user-typed / parsed from CV / GitHub
  import / answered during a form), when, and whether the user has confirmed it.
- **Every fact carries confidence.** Parsed-from-PDF is not the same as user-confirmed.
- **Facts are versioned.** Job titles change, skills grow. History is kept.
- **Nothing is silently inferred.** If Haru guesses, the guess is marked and surfaced.

### 6.2 Schema

```
PersonalBrain
│
├── identity
│   ├── legal_name, preferred_name, pronouns
│   ├── email(s), phone(s)
│   ├── address: street, city, region, country, postal_code
│   ├── date_of_birth              [sensitive]
│   ├── national_ids               [sensitive, encrypted, never to cloud]
│   └── links: linkedin, github, portfolio, website, scholar, orcid
│
├── work_authorization             ← every job form asks; most tools omit
│   ├── citizenship(s)
│   ├── legally_authorized_in: [country codes]
│   ├── requires_sponsorship: bool
│   ├── permit_type, permit_expiry
│   └── visa_status
│
├── availability
│   ├── earliest_start_date
│   ├── open_to: [full_time, part_time, contract, internship]
│   ├── notice_period
│   └── relocation_willing, remote_preference
│
├── compensation
│   ├── expectation, range_min, range_max, currency
│   └── current_salary              [sensitive, often illegal to ask — see §16.3]
│
├── education[]
│   ├── institution, degree, field, grade
│   ├── start_date, end_date (or expected)
│   ├── thesis, honors, relevant_coursework[]
│   └── transcript → document_ref
│
├── experience[]
│   ├── org, title, location, employment_type
│   ├── start_date, end_date
│   ├── summary
│   ├── achievements[]   { text, metric?, skills[], verified }
│   └── skills[], technologies[]
│
├── projects[]
│   ├── name, tagline, description
│   ├── role, team_size, duration
│   ├── technologies[], skills_demonstrated[]
│   ├── repo_url, live_url, demo_video
│   ├── outcomes[]       { text, metric?, verified }
│   ├── source: manual | github_import | devpost_import
│   └── media[]          → document_refs (screenshots, logos)
│
├── skills[]
│   ├── name, category, proficiency
│   ├── years_used, last_used
│   └── evidence[]       → refs to projects/experience that back it
│
├── credentials[]
│   ├── name, issuer, issue_date, expiry_date
│   ├── credential_id, verify_url
│   └── document_ref     ← certifications must be evidenced (P1)
│
├── writing_samples[]
│   └── past prose the user wrote, used to learn their voice — see §10.3
│
├── question_bank[]      ← recurring application questions
│   ├── canonical_question
│   ├── variants[]       ("Why us?", "Why do you want to work here?")
│   ├── base_answer
│   ├── per_target_versions[]
│   └── outcome_signal   (did submissions using this get responses?)
│
├── voluntary_disclosure [sensitive — see §16.3]
│   ├── gender, race_ethnicity, veteran_status, disability_status
│   └── default: "decline to self-identify" for all
│
├── standard_answers     ← the boring universal ones
│   ├── age_18_or_over, background_check_consent
│   ├── criminal_record, previously_employed_here
│   └── how_did_you_hear
│
├── preferences
│   ├── cv_templates[]           → see §11
│   ├── tone: formal | warm | direct | academic
│   ├── target_roles[], target_industries[], excluded_companies[]
│   └── rate_limit: max submissions per day (default: low, deliberately)
│
└── fact_boundary        ← THE ANTI-FABRICATION CONTRACT (§10.2)
    ├── allowed_skills[]         (derived from skills[] + evidence)
    ├── preserved_orgs[]
    ├── preserved_projects[]
    ├── preserved_institutions[]
    ├── real_metrics[]           (the ONLY numbers that may be cited)
    └── never_claim[]            (explicit user-set prohibitions)
```

### 6.3 Getting data in

| Method | What it does | Confidence |
| --- | --- | --- |
| CV/résumé upload | Parse PDF/DOCX → populate everything it can | Medium — requires review |
| GitHub import | Repos, languages, READMEs, commit activity → projects[] | Medium |
| Devpost import | Past hackathon submissions → projects[] | Medium |
| LinkedIn export | The official data-export ZIP, not scraping | Medium |
| Guided interview | Conversational fill of gaps | High |
| Learned from forms | Anything answered during §5 step 4 is written back | High |
| Document extraction | ID, passport, transcripts → identity + education | Medium — always confirm |

**Every import lands in a review queue.** Nothing enters the Brain as confirmed until the user
confirms it. This is P1 in practice — the fact boundary is only as trustworthy as its inputs.

---

## 7. Document Vault

Forms don't just ask questions; they demand files.

```
DocumentVault
├── documents[]
│   ├── type: cv | cover_letter | transcript | certificate | id | passport
│   │       | photo | portfolio | reference_letter | tax_doc | proof_of_address
│   ├── file (encrypted at rest)
│   ├── issued_date, expiry_date
│   ├── extracted_fields{}     → feeds the Brain, with provenance
│   ├── sensitivity: normal | sensitive | never_upload_without_asking
│   └── versions[]
└── generated[]                 ← every CV/letter Haru produced, immutably kept
    ├── source_target, template_used, content_selection
    └── outcome_link            → §15
```

**Features that fall out of this:**
- **Expiry warnings.** Passport expires in 60 days; certification lapsed last month.
- **Upload matching.** A form asks for "proof of address" — Haru knows which file that is.
- **Never-silently-upload.** Documents marked sensitive always require explicit per-use consent.

---

## 8. Target Adapters

An adapter defines: how to recognize this target type, how to extract its Ask, what the Brain
must supply, what gets generated, and how strict the gates are.

### 8.1 Job Application
- **Extract:** role, org, location, requirements, seniority, comp, deadline, ATS platform
- **Generate:** tailored CV (§11), cover letter, per-question answers from the question bank
- **Score:** fit 1–10 against the Brain; below threshold, tell the user honestly rather than applying
- **Gate:** standard approval
- **Known ATS:** Greenhouse, Lever, Workday, Ashby, SmartRecruiters, Taleo, BambooHR, Workable

### 8.2 Hackathon Submission *(requirement 3)*

The user supplies context and files; Haru writes and submits. Devpost first, then Devfolio,
DoraHacks, and generic forms.

- **Extract:** hackathon rules, theme, prize tracks, required fields, deadline, judging criteria
- **Ingest:** the repo (README, code, commit history, languages), plus user notes and media
- **Generate:** the standard Devpost story blocks — Inspiration / What it does / How we built it
  / Challenges / Accomplishments / What we learned / What's next — plus tagline, built-with tags,
  and prize-track alignment
- **Gate:** standard approval

**The distinguishing feature: submissions are grounded in the repository.**
Haru reads the actual code before describing it. If the story claims Redis and there is no Redis
in the project, that's a fact-boundary violation and it gets blocked. Hackathon write-ups are
notoriously inflated; Haru's will be accurate, which is also better for judging — judges check.

It also flags the reverse: real work in the repo that the draft failed to mention.

### 8.3 Government & Institutional Forms *(requirement 4)*

Highest stakes. False statements on official forms carry legal consequences, so this adapter
runs in **high-stakes mode**.

- **Extract:** form identity and version, required fields, required supporting documents,
  eligibility rules, fees, deadline
- **Match:** identity + documents, with **per-field confidence scores**
- **Gate:** stricter — see below
- **Output:** a complete audit record

High-stakes mode differences:

| | Standard | High-stakes |
| --- | --- | --- |
| Field confidence threshold | 0.8 auto-fill | 0.95, else ask |
| Prose generation | Allowed | **Minimal** — facts only, no persuasive writing |
| Approval | One gate before submit | Field-by-field review before submit |
| Cloud models | Allowed for prose | **Blocked entirely** |
| Evidence | Screenshot | Full record: every value, source, timestamp, hash |

**Honest limitation:** Haru assists with government forms. It is not a lawyer or an immigration
advisor and will say so, prominently, in this adapter.

### 8.4 Generic Form
The fallback. Any form Haru doesn't recognize: extract fields, match what it can, ask for the
rest, standard gates. This is what makes the product open-ended rather than a fixed list of
four things.

---

## 9. Opportunity Discovery *(requirement 1)*

The brief asks for discovery beyond job boards — Facebook, LinkedIn, independent search.

### 9.1 The design decision

There is a tempting version of this where Haru logs into Facebook and LinkedIn and scrapes the
user's feed. **We are not building that**, for two reasons: it is the exact behavior that got
AIHawk detected and abandoned, and the downside lands on the user as a suspended account —
their actual professional network.

Instead: **the Opportunity Inbox.** The user is already in their feed. Capture is passive and
happens in the session they're already sitting in.

### 9.2 Sources

| Source | Mechanism | Risk |
| --- | --- | --- |
| **Browser capture** | Extension button / right-click "Save to Haru" on anything you're looking at — a FB group post, a LinkedIn post, a Discord message, a tweet | None. You're browsing; Haru reads the page you're on. |
| **Forward to Haru** | Share from phone via Telegram/WhatsApp, or forward to a personal ingest email | None |
| **Open web search** | Haru searches the public web for matching opportunities | Low |
| **Official APIs & feeds** | Job board APIs, RSS, newsletters, Devpost/Devfolio listings | None |
| **Watched pages** | User nominates a careers page; Haru polls it politely | Low |
| **Platform data exports** | LinkedIn's official export | None |

This satisfies requirement 1 — a Facebook group post becomes an opportunity in two clicks — with
none of the ban risk. It is also *better*, because it captures the long tail that no scraper
reaches: Discord servers, private groups, newsletters, a friend's DM.

### 9.3 What happens to a captured opportunity

```
Captured → Classified (job? hackathon? grant? form?)
        → Enriched (fetch full description; three-tier: JSON-LD → selectors → model)
        → Scored against the Brain
        → Deduplicated (have we already applied to this?)
        → Deadline extracted → calendar
        → Queued for user review
```

Haru **never auto-submits from discovery.** Discovery fills a queue; the human decides.

---

## 10. Composition & the Fact Boundary

### 10.1 What gets generated
CV content selection and bullet emphasis · cover letters · application question answers ·
hackathon story sections · form free-text fields.

### 10.2 The Fact Boundary — the most important mechanism in the product

Adapted from ApplyPilot's `scoring/validator.py`, extended. Every generated artifact passes
validation before it can reach a form. Three independent checks:

**Check 1 — Fact boundary (blocking, always).**
The model may only reference skills in `allowed_skills`, organizations in `preserved_orgs`,
projects in `preserved_projects`, institutions in `preserved_institutions`, and numbers in
`real_metrics`. Adjacent technology may be mentioned as context but not claimed as experience.

**Credentials are never stretchable.** A claimed certification must have a matching entry in
`credentials[]` with a document. No exceptions, no modes.

For hackathon submissions the boundary extends to the repository: claims about what the project
does are checked against the actual code.

**Check 2 — Cliché filter.**
~50 phrases that mark text as machine-written: *passionate, dedicated, spearheaded, orchestrated,
robust, cutting-edge, proven track record, team player, self-starter, detail-oriented, synergy,
leveraged, thrives in, well-versed in.* Configurable severity.

**Check 3 — Model leakage.**
Catches the model talking to itself inside the deliverable: *"here is the revised…", "I apologize",
"as requested", "Note:", "I have updated…"*. Always blocking — this is pure output corruption.

**On failure:** regenerate with the violation fed back, up to N attempts, then stop and show the
user what it couldn't produce honestly. **Haru never degrades to submitting unvalidated content.**

### 10.3 Voice

Generated prose should sound like the user, not like an LLM. Haru learns from `writing_samples[]`
— their real cover letters, README prose, past submissions — and matches register. The cliché
filter enforces the floor; voice-matching raises the ceiling.

---

## 11. CV Generation *(requirement 2)*

The requirement: **keep my design, change what's in it.**

### 11.1 The separation

The single most important design decision here is that **presentation and content never mix.**

```
CVTemplate  (owned by user, stable)          Content (from the Brain, per target)
├── layout, fonts, spacing, colors           ├── which experiences
├── section order                            ├── which projects
├── heading labels                     ×     ├── which skills
├── slot definitions                         ├── bullet selection + emphasis
└── page rules                               └── summary text
                    ↓
              Rendered PDF
```

Tailoring changes only the right column. The design is never regenerated, so output is
**pixel-stable across every application.**

### 11.2 What tailoring may change

| Changeable | Fixed |
| --- | --- |
| Which projects appear, and their order | Fonts, colors, margins, spacing |
| Which experiences appear | Overall layout and grid |
| Section order (skills-first vs experience-first) | Page size and rules |
| **Heading labels** (*"Projects"* → *"Selected Work"*) | The template itself |
| Bullet selection and emphasis within the fact boundary | |
| Summary/objective paragraph | |
| Skills shown and their grouping | |

This matches the brief exactly: *"cv style same, just projects in and out and heading or
whatever will be changed."*

### 11.3 Getting the user's template in

**Honest constraint:** perfectly reproducing an arbitrary PDF design is not reliably achievable.
Anyone promising that is overselling. Three paths instead:

1. **Auto-extract (best effort).** Parse the user's CV, reconstruct a close-matching HTML/CSS
   template, show it side-by-side with the original, let them adjust. Good for most CVs.
2. **Bring your own template.** Upload HTML/CSS, LaTeX, or DOCX with named slots. Exact by
   construction. Best for people with an existing LaTeX CV.
3. **Start from a starter.** A small set of well-typeset templates.

Rendering: HTML/CSS → PDF via headless Chrome (deterministic, easy to tweak), with LaTeX
supported for users who already live there.

### 11.4 Review

Before any CV is used: side-by-side diff against the master, with every change highlighted and
attributed — *"Added 'Optimized query performance' bullet — matches JD requirement 'database
performance'."* Borrowed from ResumeTelling's highlighted-diff idea. The user can veto any
individual change.

Multiple named templates supported (academic CV, industry résumé, one-pager).

---

## 12. Execution Layer

### 12.1 Deterministic first

```
Target site
     ↓
Do we have a recorded adapter?
     ├── YES → replay it deterministically      ← free, fast, reproducible
     │           ↓ step fails?
     │         fall back to agent for that step
     │           ↓ recovered?
     │         HEAL the adapter → next run is deterministic again
     └── NO  → agent drives, and we RECORD it into a new adapter
```

Verified from workflow-use, which has a dedicated `healing/` module and selector-generation with
tested fallback alternatives. The consequence: the tenth Greenhouse application costs almost no
tokens, and every failure permanently improves the system. **This is the compounding moat from §2.**

### 12.2 The agent loop

Taken from NaviNate's `runTurn`, which arrived at this the hard way:

```
scan page → ask model → take EXACTLY ONE action → verify it landed → rescan → repeat
```

**One action per turn, always** — even if the model returns several, only the first fires.
Blind multi-step plans go stale the instant the page changes. NaviNate's own comment on this
is *"the real fix for the 'did it 4 times' bug."*

### 12.3 Post-action verification (P4)

NaviNate's admitted top gap; we treat it as required. After every action, confirm the observable
result before reporting success:

| Action | Verification |
| --- | --- |
| Fill field | Read the value back; confirm it matches, and that the app's state updated |
| Select dropdown | Confirm selected option |
| Click | Confirm expected state change (nav, modal, class, DOM diff) |
| Upload | Confirm filename appears in the UI |
| Submit | Confirm confirmation page / success indicator / URL change |

Unverified action = failed action. Retry, then escalate. **Haru never reports success it hasn't
observed.**

### 12.4 Framework-controlled inputs

Concrete gotcha that would otherwise cost days. Setting `element.value = x` on a React-controlled
input does **not** fire React's synthetic `onChange`. The DOM shows the text, React's state stays
empty, and the form submits blank while looking filled.

The fix, verified in NaviNate's widget:

```js
const setter = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype, "value"
).set;
setter.call(element, value);
element.dispatchEvent(new Event("input",  { bubbles: true }));
element.dispatchEvent(new Event("change", { bubbles: true }));
```

Greenhouse, Lever, and Ashby are all React. This is not an edge case.

### 12.5 Action registry

Following Cognito's pattern: the model selects from a **registry of typed, validated actions**,
not free-form code. Each action declares its parameters, preconditions, verification method, and
whether it is reversible.

`navigate · click · fill · select · check · scroll · upload · download · screenshot · extract · wait · highlight`

### 12.6 Robustness

- **Loop guard** — action signatures keyed on stable element IDs; repeat detection nudges the
  model forward before giving up (NaviNate's approach)
- **Step cap** per goal
- **State survives navigation** — goal, history, undo stack, and progress persist across page
  loads and are rebuilt on the destination page
- **Undo** — per-action reversal where the action is reversible; clearly marked where it isn't
- **Kill switch** — always-visible stop control; the agent halts immediately
- **DOM → vision fallback** for pages the DOM can't explain

### 12.7 Where the browser runs

**In the user's own browser, in their existing authenticated session.** Consequences: no password
storage, no login automation, no separate credential surface, and behavior that is simply what it
appears to be — a user's browser doing what the user asked, at human pace.

---

## 13. Model Router *(requirement 5)*

Free by default (P6), better if you pay, and never at the cost of privacy.

### 13.1 Tiers

| Tier | Runs | Used for |
| --- | --- | --- |
| **T0** Deterministic | No model | Recorded adapters, known selectors, regex, cached answers |
| **T1** Local small | 3–8B | Field matching, classification, extraction, form parsing |
| **T2** Local large | 14B+ | Prose drafts, reasoning, scoring |
| **T3** Cloud frontier | Opt-in API | Final prose polish, hard vision, complex reasoning |
| **E** Embeddings | Always local | Semantic matching, dedup, question bank |

Setup probes the machine (RAM/VRAM) and picks a working local configuration rather than asking
the user to guess.

### 13.2 Privacy rules — hard constraints

1. **Raw Personal Brain PII never goes to a cloud model.** Not identity, not national IDs, not
   voluntary disclosures, not documents.
2. Cloud calls receive the **target's text** (job description, form text) plus a **redacted,
   user-approved fact summary** — never the raw record.
3. **High-stakes mode blocks T3 entirely** (§8.3).
4. Every cloud call is logged with what was sent, inspectable by the user.

### 13.3 Cost

Per-task token and cost meter (Cognito tracks usage per thread; we do the same), a monthly
budget with a hard stop, and an always-available "this task cost $0.00 — run locally" default.

### 13.4 Honesty about local models

Local models are meaningfully worse at persuasive prose than frontier models. Haru will not
pretend otherwise. Local is the default and is genuinely good at extraction, matching, and
classification — the bulk of the work. For final prose, Haru offers a per-task upgrade and shows
the estimated cost. The user chooses, informed.

---

## 14. Safety, Approval, Evidence

### 14.1 Action classes

| Class | Examples | Gate |
| --- | --- | --- |
| **Free** | Navigate, read, scroll, screenshot, extract | None |
| **Reversible** | Fill, select, upload | None; undoable |
| **Committing** | Submit, send, pay, delete, accept terms | **Explicit approval, always** |
| **Sensitive** | Upload ID/passport, enter national ID, financial data | Explicit per-use consent |

No configuration option removes the committing-action gate. That is what P3 means.

### 14.2 The approval surface

Not a yes/no dialog. A full preview:
- Every field and the exact value that will be submitted
- Every document that will be uploaded
- Every generated document, rendered
- Diff of the tailored CV against master
- Fit score and honest reasoning
- Anything Haru is unsure about, flagged
- Actions: **Approve · Edit · Reject · Save for later**

Approval requests expire (default 24h) rather than sitting live indefinitely.

### 14.3 Evidence

Every submission produces an immutable record: timestamp, target URL, every field value and its
source, documents uploaded with hashes, generated artifacts, screenshots of the filled form and
the confirmation, full action log, and models used. Exportable.

This matters most for government forms, where "what exactly did I submit and when" is a question
with real consequences.

---

## 15. Tracker & the Outcome Loop

```
Submission
├── target, type, org, date, deadline
├── status: draft | submitted | acknowledged | in_review
│         | interview | accepted | rejected | withdrawn | expired
├── artifacts: CV version, letter, answers used
├── evidence: screenshots, action log
├── follow_ups[], reminders[]
└── outcome + notes
```

**The loop nobody closes:** correlate outcomes back to artifacts. Which CV template gets more
responses. Which question-bank answers precede interviews. Which fit-score band actually converts.

**Honesty requirement:** with small sample sizes this is noise, and Haru will say so rather than
presenting a confident-looking chart over 11 applications. Signals surface only past a threshold,
and always with the sample size attached.

Also here: deadline calendar, duplicate detection, follow-up reminders, and status-change capture.

---

## 16. Interfaces

### 16.1 Surfaces

| Surface | Role |
| --- | --- |
| **Browser extension** | Capture opportunities, side panel, watch the agent work, approve inline |
| **Desktop app** | The engine. Local models, Brain storage, document vault, browser control |
| **Chat (Telegram / WhatsApp)** | Forward opportunities, answer questions, approve, get confirmations while away |
| **Web dashboard (local)** | Brain management, templates, tracker, evidence, settings |

The desktop app is the product; the others are windows onto it. Everything runs locally with no
account required.

### 16.2 Terms of service — telling the truth

Some sites' terms prohibit automated interaction. Haru's position:

- It states plainly, per platform, what the terms say and what the realistic risk is —
  for a job site, that's account suspension on the user's main professional network
- It defaults to **human-approved, one-at-a-time, human-paced** submission, which is the lowest-risk
  posture and also the design we want for quality reasons
- It does not build evasion machinery, and it does not pretend the risk is zero
- The user decides with full information

### 16.3 Sensitive fields

`voluntary_disclosure` (gender, race, veteran, disability) defaults to *decline to self-identify*
for every field, requires explicit opt-in to set otherwise, and never leaves the device.

`current_salary` is included because forms ask, but Haru flags that this question is prohibited in
many jurisdictions and defaults to leaving it blank.

---

## 17. Build Milestones

No dates — sequenced by dependency. Each milestone ends in something demonstrably working.

| # | Milestone | Done when |
| --- | --- | --- |
| **M0** | **Brain core** — schema, local encrypted storage, CV import, review queue, provenance | You can import a CV and get a reviewable, confirmed record |
| **M1** | **Fact boundary** — validator with all three checks, plus tests with deliberate fabrication attempts | Generated text containing an unowned skill is reliably blocked |
| **M2** | **CV engine** — template/content split, import paths, tailoring, diff review, PDF render | Two jobs produce two different CVs, identical design |
| **M3** | **Execution core** — action registry, one-action loop, post-action verification, native setter, loop guard, kill switch, session persistence | A React-based ATS form is filled and every field verified |
| **M4** | **First adapter: job applications** — extraction, matching, generation, approval, evidence | End-to-end application on Greenhouse and Lever, human-approved |
| **M5** | **Local model router** — probe, tiers, T0–T2, cost meter, privacy enforcement | Full application completes with no API key and $0 cost |
| **M6** | **Adapter: hackathon submissions** — repo ingestion, story generation, repo-grounded validation, Devpost | A real submission drafted from a real repo, with inflated claims caught |
| **M7** | **Opportunity Inbox** — capture button, forwarding, classification, enrichment, scoring, dedup, deadlines | An opportunity captured from a Facebook group post reaches the queue |
| **M8** | **Adapter: government forms** — document extraction, confidence scoring, high-stakes mode, audit record | One real form completed field-by-field with full evidence |
| **M9** | **Deterministic adapters** — recording, replay, healing, adapter library | The tenth Greenhouse application uses zero tokens |
| **M10** | **Tracker & outcomes** — status, follow-ups, correlation with honest sample-size reporting | Outcomes visible; weak signals labeled weak |
| **M11** | **Chat surface** — forwarding, Q&A, remote approval | A submission approved from a phone, away from the desk |
| **M12** | **Generic form adapter** — the open-ended fallback | An unseen form type completes with human help |

**M1 before M2 is deliberate.** The validator must exist before anything generates text that
could reach a form.

---

## 18. Risks

| Risk | Severity | Response |
| --- | --- | --- |
| Fabrication reaches a real submission | **Critical** | Fact boundary (§10.2), blocking, never bypassable. Adversarial tests in M1. |
| Government form filled wrong | **Critical** | High-stakes mode, field-level review, no cloud, full audit (§8.3) |
| Site terms → user account suspended | **High** | Disclose per platform, human-paced default, user decides (§16.2) |
| ApplyPilot is simply better at jobs | **High** | Don't compete there. Cross-domain identity is the product (§2). |
| Local models too weak for good prose | **Medium** | Honest tiering; local excels at extraction/matching; opt-in upgrade for prose (§13.4) |
| CV design can't be reproduced faithfully | **Medium** | Three import paths; don't promise pixel-perfect PDF reproduction (§11.3) |
| Sites change and adapters break | **Medium** | Healing (§12.1) + agent fallback + vision |
| Brain becomes stale | **Medium** | Periodic review prompts; last-confirmed dates on facts |
| Scope sprawl across four adapters | **Medium** | One pipeline, thin adapters (§5). If an adapter needs pipeline changes, that's the signal to stop. |

---

## 19. Explicitly not building

Stated so they don't creep back in:

- **Mass-volume application mode.** No "apply to 500 jobs." Rate limits are a feature.
- **Credential storage or login automation.** Session reuse only.
- **Detection-evasion machinery.** Not an arms race we should be in.
- **Fabrication, in any mode.** No "creative" setting that relaxes the fact boundary.
- **Cloud-by-default anything.** No account required to use the product.
- **Silent submission.** No configuration removes the committing-action gate.
- **Scraping logged-in social feeds.** Capture, don't scrape (§9.1).
- **Copying Cognito's code.** BUSL-1.1. Read for ideas only.
- **Legal or immigration advice.** Assist with forms; say plainly what we are not.

---

## 20. Open questions

1. **Language/runtime.** Python has the AI ecosystem; TypeScript unifies with the extension.
   Leaning Python core + TS extension, but this is unresolved.
2. **License.** ApplyPilot is AGPL-3.0 — we cannot copy from it. Do we open-source Haru, and
   under what?
3. **Is there a "contribute upstream instead" version?** Worth genuinely considering for the job
   adapter specifically, even while building the identity layer independently.
4. **Multi-profile** — academic vs industry personas as separate Brains, or views over one?
5. **Sharing adapters.** A community library of site adapters is valuable and compounding, but
   raises trust and review questions.
6. **Which government forms first**, and in which country? This determines a lot of M8.

---

## Appendix — sources

Verified by cloning and reading source (2026-08-10):

- **ApplyPilot** — `scoring/validator.py` (fact boundary, cliché list, leak phrases),
  `profile.example.json` (schema completeness), `pipeline.py` (staged dependencies)
- **AIHawk** — `src/resume_schemas/` (Pydantic modeling); its detection history and the author's
  move to `invisible_playwright` informed §12.7 and §16.2
- **workflow-use** — `workflow_use/healing/`, controller selector generation (§12.1)
- **NaviNate** — `widget/widget.js` `runTurn` one-action loop, native value setter, loop guard,
  sessionStorage persistence; its missing post-action verification became P4
- **Browser Use** — service pattern, event bus, watchdogs, CDP recovery
- **Cognito** — action registry, per-thread usage tracking, conversation/action separation.
  **BUSL-1.1: read only.**

From descriptions only (no accessible source): Resume ArchiTech, ResumeTelling, Resume Tailor,
FormPilot, Axis, AutoApply.AI. Two GitHub URLs in the original research notes were 404s.
