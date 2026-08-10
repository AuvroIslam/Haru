# Related Work & Feature Research

## 1. Browser Automation / Web Agents

### Browser Use

* **Type:** Open-source general-purpose browser agent framework
* **Links:** [GitHub — browser-use/browser-use](https://github.com/browser-use/browser-use) · [Official site](https://browser-use.com/)
* **What it does:** Lets an LLM control a real browser to navigate, click, type, fill forms, manage tabs, take screenshots, and complete tasks. It already demonstrates job-application form filling.
* **Useful to our project:** This is probably the **best foundation** for our browser-control layer instead of building browser automation from zero.
* **Features to take:**

  * Browser navigation
  * Form filling
  * Multi-tab control
  * Screenshots
  * File uploads
  * Persistent browser sessions
  * Recovery loops
  * Domain restrictions
  * Sensitive-data masking
* **Architecture idea:**

```text
User Goal
   ↓
Task Planner
   ↓
Browser Use Agent
   ↓
Browser Session
   ↓
Website
```

---

### Browser Use TypeScript

* **Type:** TypeScript browser-agent implementation
* **Link:** [GitHub — webllm/browser-use](https://github.com/webllm/browser-use)
* **What it does:** Provides autonomous navigation, clicking, typing, forms, scrolling, tab management, vision, MCP, security restrictions and multiple LLM providers.
* **Useful to our project:** Particularly relevant if our stack is **TypeScript/Node.js**.
* **Features to take:**

  * Vision fallback
  * Multiple model providers
  * Custom browser actions
  * Domain allowlists
  * MCP
  * Browser session management
  * Observability/session recording

---

### Autonomous Web Agent

* **Type:** Hackathon browser agent
* **Links:** [Devpost](https://devpost.com/software/autonomous-web-agent) · ~~GitHub~~ (`github.com/andrewbaggio1/autonomous-web-agent` returns 404 — verified 2026-08-10; no public source)
* **What it does:** Uses **two different browser agents**:

  * DOM-based agent for traditional websites
  * Vision-based agent for websites with hidden/difficult DOMs.
* **Useful to our project:** This solves one of our biggest problems: websites don't all expose useful HTML.
* **Feature to take:**

  * **DOM → Vision fallback**
* **Architecture:**

```text
              Website
                 ↓
          Can DOM understand it?
             ↙       ↘
           YES        NO
            ↓          ↓
        DOM Agent   Vision Agent
             ↘      ↙
               Action
```

---

## 2. Autonomous Agent Architecture

### REAL Hackathon Browser Agent

* **Type:** Winning browser-agent hackathon project
* **Links:** [Devpost](https://devpost.com/software/real-hackathon-browser-agent) · ~~GitHub~~ (`github.com/PeixiXie/real-agent` returns 404 — verified 2026-08-10; no public source)
* **What it does:** Handles jobs/forms, emails, calendar events, hotel booking and multi-page browser workflows. It experimented with reflection and eventually added an **orchestrator architecture**.
* **Why useful:** We shouldn't have one LLM blindly controlling everything.
* **Features to take:**

  * Task orchestration
  * Reflection/self-checking
  * Error recovery
  * Multi-step planning
  * State tracking
* **Architecture:**

```text
              User Goal
                  ↓
             Orchestrator
                  ↓
        ┌─────────┴─────────┐
        ↓                   ↓
     Planner             Browser
        ↓                 Worker
        └─────────┬─────────┘
                  ↓
              Validator
                  ↓
          Success / Retry
```

---

## 3. Cognito — Autonomous Browser Agent

### Cognito

* **Type:** Chrome browser agent / hackathon project
* **Links:** [Devpost — Cognito Browser Agent](https://devpost.com/software/cognito-your-ai-browser-agent) · [GitLab source code](https://gitlab.com/codewarnab-group/cognito-ai)
* **What it does:** Lives in a Chrome side panel and supports browser automation, research, contextual RAG, multi-step tasks, MCP, local AI, memory and voice interaction.
* **Useful to our project:** Very close to our desired **browser-extension UX**.
* **Features to take:**

  * Side-panel interface
  * Natural-language commands
  * Context-aware webpage interaction
  * PDF/page/video understanding
  * Local AI mode
  * Persistent memory
  * MCP integration
  * Multi-step workflows
  * Human approval for sensitive actions
  * Prompt-injection defense
* **Important architecture idea:**

```text
Chrome Extension
      ↓
Conversation Agent
      ↓
Browser Action Agent
      ↓
Browser Tools
      ↓
Website
```

Cognito specifically separates conversation from browser execution, which is a good design for our project.

---

## 4. Axis — Voice Browser Agent

### Axis

* **Type:** 2026 Gemini Live hackathon project
* **Link:** [Devpost](https://devpost.com/software/axis-voice-driven-browser-agent)
* **What it does:** User talks naturally while the agent watches the screen and clicks, types, scrolls and navigates. It also supports uploaded PDFs/images and session history.
* **Useful to our project:** Shows how the agent can become an **interaction layer**, rather than simply a chatbot.
* **Features worth taking:**

  * Screen understanding
  * File upload as context
  * Persistent sessions
  * Interruptible interaction
  * Voice as an optional interface
  * iframe handling
* **Not MVP:** Voice isn't necessary initially.

---

## 5. AutoApply.AI

### AutoApply.AI

* **Type:** Hackathon job-application automation
* **Link:** [Devpost](https://devpost.com/software/auto-apply-ai)
* **What it does:** Finds jobs, sends the user a summary, waits for a **YES**, automatically fills/submits applications and sends a confirmation screenshot. It uses Playwright and Telegram notifications.
* **This is VERY relevant to our project.**
* **Features to take:**

  * Application profile
  * Automated form filling
  * Telegram communication
  * Confirmation screenshots
  * User approval before applying
  * Application history
* **Workflow to copy conceptually:**

```text
Find opportunity
      ↓
Analyze
      ↓
Prepare application
      ↓
"Ready to submit?"
      ↓
User: YES
      ↓
Submit
      ↓
Screenshot + confirmation
```

This is almost exactly the **WhatsApp/Telegram agent interaction** we discussed.

---

# 6. Resume ArchiTech

### Resume ArchiTech

* **Type:** HackPrinceton 2024 winning project
* **Link:** [Devpost](https://devpost.com/software/resume-architech)
* **Award:** Best Education Hack + Best Use of AI for Interview Process.
* **What it does:** Automatically selects the most relevant projects/work experiences for a job, uses GitHub data, semantic search and LLMs to generate tailored resume content.
* **Why useful:** This directly validates your friend's **“which projects should I include?”** idea.
* **Features to take:**

  * GitHub project importing
  * Semantic project matching
  * Job-description analysis
  * Relevant-project selection
  * AI-generated bullets
  * Automated CV generation
* **Architecture:**

```text
Job Description
       ↓
Requirement Extraction
       ↓
Semantic Matching
       ↓
User's Projects
       ↓
Relevant Projects
       ↓
Tailored CV
```

---

# 7. Resume Tailor

### Resume Tailor

* **Type:** AI resume optimization project
* **Link:** [Devpost](https://devpost.com/software/resume-tailor)
* **What it does:** Extracts information from a resume, analyzes a job description, identifies keywords and requirements, then restructures the resume around the target job.
* **Useful to our project:** Gives us the **job → resume customization** layer.
* **Features to take:**

  * Job-description parsing
  * Keyword extraction
  * ATS optimization
  * Resume restructuring
  * Multiple-language support
  * Optimization analytics

---

# 8. Resume Tailor Extension

### Resume Tailor Extension

* **Type:** Chrome extension using local Chrome AI
* **Link:** [Devpost](https://devpost.com/software/resume-tailor-extension)
* **What it does:** User can right-click a job posting and generate a tailored cover letter locally using Gemini Nano; it supports offline processing and multiple languages.
* **Useful to our project:** Strong evidence for your **local LLM/privacy** idea.
* **Features to take:**

  * Local AI
  * Offline processing
  * Context-menu action
  * Resume parsing
  * Cover-letter generation
  * PDF/DOCX export
* **Great UX idea:**

> Right-click job posting → **“Apply with my AI agent”**

Instead of making users open another application.

---

# 9. ResumeTelling

### ResumeTelling

* **Type:** 2026 agentic career copilot
* **Link:** [Devpost](https://devpost.com/software/resume-telling)
* **What it does:** Parses resumes, tailors them to jobs, performs semantic skill matching, generates cover letters, and creates STAR interview stories. It also shows a highlighted diff before saving changes.
* **Useful to our project:** Gives us a much richer **personal career brain**.
* **Features to take:**

  * Structured personal profile
  * Semantic skill matching
  * Tailored CV
  * Cover letter
  * STAR stories
  * Highlighted changes/diff
  * Interview preparation
* **Especially useful:**

```text
Master Profile
      ↓
Job Description
      ↓
Relevant experiences
      ↓
CV
      ↓
Cover Letter
      ↓
Application Answers
```

---

# 10. Browser Memory Extension

### Browser Memory Extension

* **Type:** Local AI memory layer
* **Link:** [Devpost](https://devpost.com/software/browser-memory-extension)
* **What it does:** Compresses browsing activity into reusable context and uses local gpt-oss models to understand user behavior and provide relevant context to AI tools.
* **Useful to our project:** This is extremely relevant to our **Personal Brain**.
* **Features to take:**

  * Persistent memory
  * Local memory processing
  * Context compression
  * Workflow pattern recognition
  * Personalization
  * Local LLM
  * Future MCP memory interface
* **Our version:**

```text
Personal Brain

Facts
 ├── Skills
 ├── Projects
 ├── Education
 └── Experience

Preferences
 ├── CV style
 ├── Project preferences
 └── Application preferences

Documents
 ├── CV
 ├── Certificates
 └── Portfolio

Past Actions
 ├── Applications
 ├── Successful workflows
 └── Failed workflows
```

---

# 11. FormPilot Enterprise

### FormPilot Enterprise

* **Type:** Government-form AI agent
* **Link:** [Devpost](https://devpost.com/software/formpilot-enterprise)
* **What it does:** Extracts identity information from documents, maps it into government forms, performs eligibility/compliance reasoning, generates PDFs and uses human-in-the-loop workflows.
* **Useful to our project:** Directly relevant to the **government website problem** we originally identified.
* **Features to take:**

  * Document → structured information
  * Intelligent field mapping
  * Confidence scoring
  * Human approval
  * Compliance validation
  * Audit trail
  * Multi-document information extraction
* **Architecture:**

```text
ID / PDF / Document
       ↓
Document Understanding
       ↓
Structured Personal Data
       ↓
Form Field Mapping
       ↓
Validation
       ↓
Human Approval
       ↓
Submission
```

---

# 12. General Browser-Use Architecture

The Browser Use ecosystem itself has several useful open-source pieces beyond the main agent, including a browser harness, desktop app, workflow/RPA system, Telegram-enabled browser box, and browser-native agent framework.

### Particularly interesting:

**Browser Harness**

* Self-healing browser automation.
* Useful for recovering when webpage structure changes.

**Workflow Use**

* More deterministic workflow/RPA layer.
* Useful for tasks that should execute predictably rather than letting an LLM improvise every step.

**Browser Use Box**

* Browser agent + Telegram + real browser.
* **Very relevant to our WhatsApp/Telegram concept.**

---

# 12b. Verified Projects — Cloned and Read (2026-08-10)

> Everything above this line was gathered from web/Devpost descriptions. The projects in **this**
> section were actually cloned and their source read. Findings here are verified.

## ApplyPilot — the closest thing to our product that already exists

* **Type:** Production open-source autonomous job-application pipeline (Python, AGPL-3.0)
* **Link:** [GitHub — Pickle-Pixel/ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot)
* **Claim:** "Applied to 1,000 jobs in 2 days. Fully autonomous."
* **This overlaps ~70% of our proposed PRD.** We must read it before building.

**Its 6-stage pipeline** (`src/applypilot/pipeline.py`), with a strict upstream dependency chain
`discover → enrich → score → tailor → cover → pdf`, then a separate `apply` stage:

| Stage | What it does |
| --- | --- |
| Discover | JobSpy scrape (Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs) + 48 Workday portals + 30 direct career sites |
| Enrich | Full JD via JSON-LD → CSS selectors → AI extraction (three-tier fallback) |
| Score | LLM rates fit 1–10; only high-fit jobs proceed |
| Tailor | Per-job resume rewrite, **validated against fabrication** |
| Cover | Per-job cover letter |
| PDF | Render tailored resume + letter |
| Apply | Drives Chrome via **Playwright MCP**, fills, uploads, answers, submits |

**The single most valuable thing to steal — `scoring/validator.py`:**
An anti-fabrication validator that runs on every generated document. Three modes
(`strict` / `normal` / `lenient`). It checks:

* `BANNED_WORDS` — ~50 LLM clichés ("passionate", "spearheaded", "robust", "team player",
  "proven track record", "detail-oriented"). Strict mode makes these hard errors that trigger regeneration.
* `LLM_LEAK_PHRASES` — catches the model talking to itself in the output
  ("here is the revised", "i apologize", "as requested", "note:").
* `FABRICATION_WATCHLIST` — languages/frameworks/certs the candidate demonstrably doesn't have.
  Notably it *allows* reasonable stretches (K8s, Terraform, Redis) but blocks hard lies,
  especially certifications, which "can't be stretched."
* `REQUIRED_SECTIONS` — structural check on the resume.

Fabrication limits are **profile-driven, not hardcoded**: the profile carries a
`skills_boundary` (the allowed skill set) and `resume_facts` with `preserved_companies`,
`preserved_projects`, `preserved_school`, and `real_metrics`. The LLM may reorganize and
re-emphasize within that boundary but may not invent outside it.

**Its profile schema (`profile.example.json`) — richer than what we drafted.** Fields our PRD
missed entirely and that essentially *every* real job application asks for:

* `work_authorization` — legally authorized, requires sponsorship, permit type
* `availability` — earliest start date, full-time vs contract
* `compensation` — expectation, min/max range, currency
* `eeo_voluntary` — gender, race/ethnicity, veteran status, disability status
* Canned standard answers — age 18+, background check, felony, previously worked here, how heard

## AIHawk (Jobs_Applier_AI_Agent_AIHawk)

* **Type:** The original mass job-application bot (Python, MIT)
* **Link:** [GitHub — feder-cr/Jobs_Applier_AI_Agent_AIHawk](https://github.com/feder-cr/jobs_applier_ai_agent_aihawk)
* **Scope:** LinkedIn Easy Apply only; template-based resume rather than per-job rewrite.
* **Schema to borrow:** `src/resume_schemas/resume.py` is a clean Pydantic model set —
  `PersonalInformation`, `EducationDetails`, `ExperienceDetails`, `Project`, `Achievement`,
  `Certifications`, `Language`, `Availability`, `SalaryExpectations`, `SelfIdentification`,
  `LegalAuthorization`. Plus a separate `job_application_profile.py`.

**The warning it carries is as useful as the code.** AIHawk was covered by TechCrunch, Wired,
The Verge, and 404 Media — largely critically ("AI is enabling job seekers to think like
spammers"; one reporter auto-applied to 2,843 roles). Its author has since moved on to
[invisible_playwright](https://github.com/feder-cr/invisible_playwright), a patched-Firefox
Playwright replacement, because **AIHawk kept getting detected as a bot at scale**. Their docs
cover why an attached debugger is detectable and why automating login is riskier than reusing a
session.

Two consequences for us, neither of which our PRD acknowledged:

1. **Bot detection is a first-class engineering constraint**, not an edge case. Standard
   Playwright/CDP automation is detectable, and job platforms actively detect it.
2. **Volume is a reputational and ToS liability.** The "apply to 1,000 jobs" framing is exactly
   what drew the backlash. Our differentiator should be *quality per application*, not throughput.

## Workflow Use (Browser Use org)

* **Link:** [GitHub — browser-use/workflow-use](https://github.com/browser-use/workflow-use)
* **What it is:** "Deterministic, self-healing workflows (RPA 2.0)". You record a workflow once;
  it replays deterministically and **falls back to a Browser Use agent only when a step fails**.
* **Verified structure:** `workflow_use/` splits into `recorder/`, `builder/`, `workflow/`,
  `controller/`, `healing/`, `storage/`, `schema/`, `mcp/`. There is a dedicated `healing/` module,
  and the controller carries element-finder / selector-generator / xpath-optimization logic with
  tested "max alternatives" fallback behavior.
* **Why this matters to us:** it is the right answer to the reliability problem. Deterministic
  replay for the 90% case, LLM agent only for the 10% that broke. Cheaper and far more reliable
  than letting an LLM improvise every step, every time.
* **Caveat from its own README:** "very early development, we don't recommend using this in production."

## NaviNate — the opposite side of the transaction

* **Type:** Hack the 6ix 2026 winner (Best Beginner Hack + Base44 challenge). ~5.6K LOC.
* **Link:** [GitHub — katiehclau-art/NaviNate](https://github.com/katiehclau-art/NaviNate)
* **What it is:** An embeddable voice-enabled widget a **company** installs on **its own** site to
  guide **its** visitors. Vanilla JS widget + Node/Express backend + Base44 control plane +
  ElevenLabs voice.

**Why it matters strategically:** it is the same technology as a user-side browser agent, aimed
the other way round. Because the site owner installs it, NaviNate has no bot-detection problem,
no ToS problem, and no CDP fingerprint — it's just in-page JavaScript. It sidesteps the two
risks that killed AIHawk by choosing a different side of the table. It is **not** a competitor to
Haru (no personal brain, no documents, no cross-site identity), but it's a useful proof that
positioning matters more than pipeline.

**Four techniques verified in `widget/widget.js` (3,055 lines) and adopted in our PRD:**

1. **One action per turn, then rescan.** `runTurn` deliberately executes only `data.actions[0]`
   even when the model returns several. Its own comment: *"the real fix for the 'did it 4 times'
   bug."* Blind multi-step plans go stale the moment the page changes.
2. **Native value setter for framework-controlled inputs.** Plain `el.value = x` does not fire
   React's synthetic `onChange`, so React state stays empty and the form submits blank while
   looking filled. They use
   `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set` then dispatch
   `input` + `change`. Greenhouse, Lever and Ashby are all React — this is not an edge case.
3. **Loop guard on stable element IDs**, nudging the model forward a few times before giving up.
4. **`sessionStorage` persistence across navigation** — page nav destroys the JS context, so goal,
   history, undo stack and nav state are saved and the widget rebuilds on the destination page.

**Their admitted top gap, which we treat as a principle:** no deterministic post-action
verification. NaviNate reports success without confirming the field actually changed. It's the
first item on their "what's next." This became **PRD P4 — verify, don't assume**.

**Honest calibration:** beginner-category win; single model (`gpt-4o`, no fallback); 262-line
crawler; Base44 is a sponsor-challenge dependency they'd need to unwind. Undo is also shallower
than the writeup implies — form fields restore directly, but application state (cart contents)
requires the host company to implement an adapter contract.

## Cognito — verified extension architecture

* **Link:** [GitLab — codewarnab-group/cognito-ai](https://gitlab.com/codewarnab-group/cognito-ai)
* **License:** BUSL-1.1 — **source-available, not open source.** We can read it for ideas but
  cannot copy code into an AGPL/MIT product. Worth noting before anyone lifts a file.
* **Verified layout:** pnpm/turbo monorepo — `apps/{extension,webapp,docs}` and
  `packages/{backend-vercel,backend-cloudflare,cli-bridge,shared}`.
* **Extension internals** (`apps/extension/src/`): `ai/` is split into `agents`, `planning`,
  `prompts`, `tools`, `models`, `mcp`, `stream`, `transport`, `cliMode`. Actions are a registry
  (`actions/registerAll.ts`) over `dom`, `interactions`, `tabs`, `screenshot`, `history`,
  `bookmarks`, `search`, `selection`. Workflows are a separate registry with a `sessionManager`.
  Local persistence in `db/` (threads, messages, settings, storedPDFs, usage).
* **The pattern worth copying:** a **registry of typed actions** that the planner selects from,
  rather than free-form LLM control. Plus `usage.ts` — they track token spend per thread.

---

# 13. Architecture Ideas We Should Combine

After looking at all of these, I think our architecture should be:

```text
                         USER
                          │
             ┌────────────┼────────────┐
             │            │            │
          Chrome       WhatsApp     Telegram
          Extension       │            │
             │            └─────┬──────┘
             └──────────────────┤
                                ↓
                     ┌────────────────────┐
                     │   TASK MANAGER     │
                     │                    │
                     │ Understand Goal    │
                     │ Break into Steps   │
                     │ Track State        │
                     └─────────┬──────────┘
                               ↓
                     ┌────────────────────┐
                     │    ORCHESTRATOR    │
                     └─────────┬──────────┘
                               ↓
               ┌───────────────┼────────────────┐
               ↓               ↓                ↓
        Personal Brain    Document Agent   Browser Agent
               │               │                │
               ↓               ↓                ↓
        User Information    CV/PDF        DOM + Vision
               │               │                │
               └───────────────┼────────────────┘
                               ↓
                         VALIDATOR
                               ↓
                    ┌──────────┴──────────┐
                    ↓                     ↓
                 Continue             Ask User
                    │                     │
                    └──────────┬──────────┘
                               ↓
                        APPROVAL GATE
                               ↓
                            SUBMIT
                               ↓
                      Screenshot + Log
                               ↓
                     Application Tracker
```

---

# 14. Feature Ideas We Should Take

| Feature                 | Inspiration                    | Use in Our Product             |
| ----------------------- | ------------------------------ | ------------------------------ |
| Browser navigation      | Browser Use                    | Core browser agent             |
| DOM + Vision            | Autonomous Web Agent           | Handle difficult websites      |
| Orchestrator            | REAL Agent                     | Reliable multi-step tasks      |
| Reflection              | REAL Agent                     | Check/retry failed actions     |
| Side panel              | Cognito                        | Main extension UI              |
| Local AI                | Cognito / Resume Tailor        | Privacy                        |
| Personal memory         | Browser Memory                 | Personal Brain                 |
| Project matching        | Resume ArchiTech               | Pick relevant projects         |
| CV tailoring            | Resume Tailor                  | Job-specific CV                |
| Semantic matching       | ResumeTelling                  | Match user to opportunity      |
| Cover letters           | Resume Tailor Extension        | Generate application documents |
| Document extraction     | FormPilot                      | Fill forms from documents      |
| Confidence              | FormPilot                      | Know when to ask user          |
| Human approval          | FormPilot / Cognito / G-Axis   | Safe submission                |
| Screenshot confirmation | AutoApply.AI                   | Proof of work                  |
| Telegram control        | AutoApply.AI / Browser Use Box | Remote agent control           |
| Application tracker     | AutoApply.AI                   | Track submissions              |
| Session history         | Axis                           | Resume interrupted tasks       |
| MCP                     | Cognito                        | Connect external services      |
| Context menu            | Resume Tailor Extension        | “Apply with agent” shortcut    |
| Failure memory          | Browser Memory / research      | Learn successful workflows     |
| Audit log               | FormPilot                      | Explain what agent did         |

---

# 15. What Makes **Our** Product Different

This is the most important part.

We shouldn't build:

> **“Another AI browser agent.”**

Because Browser Use, Cognito, REAL Agent, Axis and many others already cover that territory.

We also shouldn't build:

> **“Another AI resume tailor.”**

Resume ArchiTech, Resume Tailor and ResumeTelling already cover that.

### Our combination should be:

```text
                 PERSONAL AI
                     │
        ┌────────────┼────────────┐
        ↓            ↓            ↓
   KNOWS YOU     KNOWS TASK    KNOWS WEB
        │            │            │
 Projects       Goal/Intent    Browser
 Skills         Opportunity    Navigation
 Experience     Requirements   Forms
 Documents                     Websites
 Preferences
        │            │            │
        └────────────┼────────────┘
                     ↓
              DOES IT FOR YOU
```

### The core thesis:

> **You don't operate the website. You tell the agent the outcome you want, and it represents you on the web.**

For example:

> **“Apply to this internship.”**

The agent determines:

1. What the company wants.
2. Whether you're a reasonable match.
3. Which of your projects are relevant.
4. Which CV version to create.
5. What application answers to generate.
6. How to navigate the website.
7. Which information it already knows.
8. What information it still needs.
9. What it should ask you.
10. What needs your approval.
11. What to submit.
12. What evidence to save afterward.

That **end-to-end combination** is the actual opportunity.

---

# 16. Recommended MVP Architecture

For a hackathon, I would **not build every feature above**.

### Phase 1 — The killer demo

```text
Chrome Extension
       ↓
Natural Language Task
       ↓
Orchestrator
       ↓
Browser Use
       ↓
DOM + Vision
       ↓
Form Filling
       ↓
Screenshot
       ↓
Approval
       ↓
Submit
```

### Phase 2 — Personal Intelligence

```text
Personal Brain
      ↓
Projects
Skills
CV
Experience
Documents
      ↓
Application Agent
```

### Phase 3 — Communication

```text
WhatsApp / Telegram
       ↓
Agent
       ↓
"Need your graduation date."
       ↓
User replies
       ↓
Agent continues
```

### Phase 4 — Career Intelligence

```text
Opportunity
     ↓
Fit Score
     ↓
Relevant Projects
     ↓
Tailored CV
     ↓
Tailored Answers
     ↓
Application
     ↓
Tracker
```

---

## 17. The 5 projects I'd study most deeply

If you're going to actually inspect code rather than just read descriptions, I'd prioritize:

1. **[Browser Use GitHub](https://github.com/browser-use/browser-use)** — browser-agent foundation.
2. **[REAL Hackathon Browser Agent](https://devpost.com/software/real-hackathon-browser-agent)** — orchestration + reliability.
3. **[Cognito Devpost](https://devpost.com/software/cognito-your-ai-browser-agent)** / [Cognito source](https://gitlab.com/codewarnab-group/cognito-ai) — extension + local AI + memory + MCP.
4. **[Resume ArchiTech](https://devpost.com/software/resume-architech)** — project selection + semantic matching.
5. **[AutoApply.AI](https://devpost.com/software/auto-apply-ai)** — application automation + Telegram + screenshot confirmation.

Those five cover almost the entire foundation of what we're trying to build.

**One caveat:** several Devpost pages expose a generic “github.com” button but don't expose the repository URL in the indexed page, so I have **not invented GitHub URLs** for those projects. Where I could verify an actual repository URL, I've linked it directly.

