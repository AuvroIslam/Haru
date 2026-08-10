# Haru - Personal AI Web Agent
## Comprehensive Product Requirements Document

---

## 1. Executive Summary

**Product Name:** Haru (Personal AI Web Agent)

**Vision:** Build an end-to-end AI agent that doesn't just automate websites, but *represents you on the web*. Users don't operate websites—they tell Haru what they want, and it figures out how to do it while staying true to who they are.

**Core Thesis:** 
> You don't operate the website. You tell the agent the outcome you want, and it represents you on the web.

**Example Use Case:**
User: *"Apply to this internship"*
Agent determines:
1. What the company wants (job requirements)
2. If you're a reasonable match (fit scoring)
3. Which of your projects are relevant (semantic matching)
4. Which CV version to create (tailored to opportunity)
5. What application answers to generate (based on Personal Brain)
6. How to navigate the website (browser automation)
7. Which information it already knows (from Personal Brain)
8. What information it still needs (asks user)
9. What needs your approval (sensitive actions)
10. What to submit (filled forms)
11. What evidence to save (screenshots + audit log)

---

## 2. Key Differentiators

Unlike existing solutions, Haru combines three layers:

### Layer 1: KNOWS YOU (Personal Brain)
- Projects & project descriptions
- Skills and expertise areas
- Education and certifications
- Experience and work history
- Documents (CV, portfolio, certificates)
- Personal preferences (CV style, application tone, industry preferences)
- Past application attempts and outcomes (success patterns)

### Layer 2: KNOWS THE TASK (Task Intelligence)
- Goal/intent understanding ("Apply to job X" vs "Download file Y")
- Opportunity analysis (parse job descriptions, extract requirements)
- Match analysis (semantic matching between user and opportunity)
- Context awareness (which Personal Brain data is relevant)

### Layer 3: KNOWS THE WEB (Browser Agent)
- Reliable browser automation (built on Browser Use)
- DOM parsing + Vision fallback (handles complex websites)
- Form field understanding (matches HTML fields to user data)
- Multi-page workflow navigation
- Error recovery and self-healing
- Screenshot evidence capture

**The Combination = Powerful & Differentiated**
Not another "AI browser agent" (those exist: Browser Use, Cognito, REAL Agent)
Not another "AI resume tailor" (those exist: Resume ArchiTech, ResumeTelling)
But a **personal AI that knows you, knows the task, and knows the web** to do your applications end-to-end.

---

## 3. User Personas

### Primary User: Career-Stage Professionals
- Age: 22-35 (internships, early-career roles, career transitions)
- Pain: Spending hours on repetitive job applications across different websites
- Goal: Apply to more opportunities without application fatigue
- Motivation: Quality over quantity—better tailored applications

### Secondary User: Career Switchers
- Age: 30-50+ (changing industries, returning to work)
- Pain: Unsure which past projects/skills are relevant to new field
- Goal: Highlight transferable skills while staying authentic
- Motivation: Confidence + speed in application process

### Tertiary User: Portfolio-Heavy Applicants
- Age: 22-40 (engineers, designers, creatives)
- Pain: Manually tailoring portfolio + CV + answers for each application
- Goal: Automated but authentic customization
- Motivation: Show best projects for each opportunity

---

## 4. Core Features

### Tier 1 - MVP Features (Phase 1: Killer Demo)

#### 4.1 Goal-Based Browser Automation
**What:** User provides high-level goal; agent figures out the steps
- *"Apply to this job link"*
- *"Download the latest version of [software]"*
- *"Fill out this form"*

**How:**
1. Parse user's natural-language goal
2. Load the webpage
3. Analyze DOM + take screenshot (vision fallback if needed)
4. Break goal into step-by-step actions
5. Execute with feedback loops

**Technical Approach:**
- Use Browser Use as foundation for automation
- Orchestrator pattern: goal → planner → executor → validator
- Reflection: "Did that work? If not, try another approach"

---

#### 4.2 Smart Form Filling
**What:** Agent reads entire form, matches fields to user's stored data, fills automatically
- Extracts all form fields from DOM
- Matches field labels to known user data types (name, email, phone, etc.)
- Auto-fills with high confidence
- Asks user only for unknown data
- Handles different input types: text, select, radio, checkbox, file upload

**Data Mapping:**
```
Form Field → User Data Type → Value
"Full Name" → name → "Alice Chen"
"Email Address" → email → "alice@example.com"
"Phone" → phone → "+1-555-0123"
"Your Background" → experience_summary → [from Personal Brain]
```

---

#### 4.3 Ask-When-Needed Intelligence
**What:** Instead of overwhelming user, agent asks only for truly unknown information
- Analyzes form before asking
- Checks Personal Brain for matching data
- Only asks for information it genuinely doesn't know
- Smart follow-ups (e.g., if missing graduation year, asks "When did you graduate from X?")

**Question Priority:**
1. Can it be found in Personal Brain? (auto-fill)
2. Can it be inferred from context? (ask with suggestion)
3. Doesn't exist anywhere? (ask user)

---

#### 4.4 DOM + Vision Fallback
**What:** Start with reliable DOM parsing; fall back to vision when DOM is insufficient
- First attempt: Parse form via HTML/DOM analysis
- Detection: Is DOM insufficient? (hidden fields, dynamic elements, complex layouts)
- Fallback: Take screenshot, use vision model to understand form
- Advantage: Works on traditional websites AND complex SPAs

**Use Cases:**
- Traditional HTML forms → pure DOM
- JavaScript-heavy applications → vision
- Hidden/obfuscated forms → vision
- PDF forms embedded in webpage → vision

---

#### 4.5 Screenshot Evidence Capture
**What:** Take screenshots after key actions for audit trail + user verification
- Screenshot after form fill (before submit)
- Screenshot after successful submission
- Screenshot on error (for debugging)
- User can review before approving submission

---

#### 4.6 Approval Gates
**What:** Agent can freely navigate and fill, but asks before critical actions
- **Free actions:** Navigate, click, type, scroll, screenshot
- **Approval required:** Submit, Send, Pay, Delete, Login (new account)
- **Silent actions:** Fill forms, analyze pages

**Flow:**
```
Agent: "Ready to submit application?"
User: "Yes / No / Let me review"
→ Show screenshot of filled form
→ Allow edits if needed
→ Then proceed with submission
```

---

### Tier 2 - Personal Brain Features (Phase 2)

#### 4.7 Personal Brain - Data Storage
**What:** Structured repository of user's professional information
```
Personal Brain
├── Identity
│   ├── Full name
│   ├── Email
│   ├── Phone
│   └── Location
├── Projects
│   ├── Project name
│   ├── Description
│   ├── Technologies
│   ├── GitHub/Link
│   └── Impact metrics
├── Skills
│   ├── Technical skills (with proficiency levels)
│   ├── Soft skills
│   └── Certifications
├── Experience
│   ├── Job title
│   ├── Company
│   ├── Duration
│   ├── Description
│   └── Key achievements
├── Education
│   ├── School name
│   ├── Degree
│   ├── Graduation date
│   └── GPA/honors
├── Documents
│   ├── Master CV
│   ├── Certificates
│   ├── Portfolio links
│   └── Cover letter templates
├── Preferences
│   ├── CV style/design (formal, modern, creative)
│   ├── Application tone (professional, enthusiastic, etc.)
│   ├── Industry preferences
│   └── Company size preferences
│
├── Work Authorization          ← REQUIRED, was missing
│   ├── Legally authorized to work (Yes/No)
│   ├── Requires sponsorship (Yes/No)
│   └── Work permit type
├── Availability                ← REQUIRED, was missing
│   ├── Earliest start date
│   ├── Open to full-time (Yes/No)
│   └── Open to contract (Yes/No)
├── Compensation                ← REQUIRED, was missing
│   ├── Salary expectation
│   ├── Range min / max
│   └── Currency
├── EEO Voluntary Disclosure    ← REQUIRED, was missing
│   ├── Gender (default: decline to self-identify)
│   ├── Race/ethnicity (default: decline to self-identify)
│   ├── Veteran status
│   └── Disability status
├── Standard Answers            ← was missing
│   ├── Age 18+ / background check consent / felony
│   ├── Previously worked here
│   └── How did you hear about us
│
└── Fact Boundary               ← ANTI-FABRICATION, was missing
    ├── skills_boundary (the ONLY skills the LLM may claim)
    ├── preserved_companies
    ├── preserved_projects
    ├── preserved_school
    └── real_metrics (the only numbers the LLM may cite)
```

**Why the four "REQUIRED, was missing" blocks matter:** essentially every real job application
asks for work authorization, availability, salary expectation, and EEO disclosure. An agent
that cannot answer these cannot complete a single application unattended. This was verified
against ApplyPilot's `profile.example.json` and AIHawk's `resume_schemas/`.

**EEO handling is sensitive.** These are protected-characteristic questions. Defaults must be
"decline to self-identify," the user must explicitly opt in to any other value, and these
fields must never be sent to a cloud LLM.

---

#### 4.7b Anti-Fabrication Validator (borrowed from ApplyPilot)

**What:** Every LLM-generated resume, cover letter, or application answer is validated before
it reaches a form. This is the difference between a useful assistant and one that lies on your
behalf — lying on a job application is a real harm to the user.

**Three checks, all profile-driven:**

1. **Fact boundary.** The model may only claim skills in `skills_boundary`, companies in
   `preserved_companies`, projects in `preserved_projects`, and numbers in `real_metrics`.
   Reasonable adjacent tech is allowed; unrelated languages/frameworks are blocked.
   **Certifications are never stretchable** — a claimed cert is either real or it's fraud.
2. **Banned clichés.** ~50 phrases that make output read as machine-written: "passionate",
   "spearheaded", "robust", "proven track record", "team player", "detail-oriented".
3. **LLM leak detection.** Catches the model talking to itself in the deliverable:
   "here is the revised…", "i apologize", "as requested", "note:".

**Modes:** `strict` (violations force regeneration) / `normal` (clichés warn, fabrication
errors) / `lenient` (fabrication only). Default `normal`.

**Failure behavior:** regenerate up to N times, then surface to the user rather than
submitting unvalidated content.

**Data Entry Methods:**
- Manual upload of CV/resume (parse to extract info)
- GitHub profile import (pull projects + languages)
- Manual form entry (guided workflow)
- Document upload (PDFs, images → extract via OCR/vision)

---

#### 4.8 Smart Project Selection
**What:** Automatically choose most relevant projects for each opportunity
- Parse job description → extract required skills/keywords
- Analyze user's projects → extract skills/keywords
- Semantic matching: Which projects showcase the right skills?
- Rank by relevance to opportunity

**Example:**
```
Job: "Seeking fullstack engineer for React+Node startup"
Available projects:
  • ChatApp (React, Node.js, WebSockets) - Score: 95%
  • DataViz Dashboard (Python, Matplotlib) - Score: 30%
  • CLI Tool (Go, REST APIs) - Score: 50%

→ Auto-select ChatApp + highlight relevant parts
```

---

#### 4.9 Dynamic CV Generation
**What:** Create tailored CV for each opportunity while preserving user's style
- Start with master CV template
- Reorder sections based on relevance (skills-first for technical job, experience-first for leadership)
- Choose relevant projects/experiences
- Customize bullet points to highlight relevant skills
- Maintain original design/formatting preferences

**Customization Layers:**
1. Section reordering (what comes first?)
2. Content selection (which projects/roles?)
3. Bullet point tailoring (emphasize relevant achievements)
4. Design preservation (keep user's CV aesthetic)

---

#### 4.10 Application Answer Generation
**What:** Generate answers for open-ended application questions using Personal Brain
- Parse application question
- Identify what skills/experiences it's asking for
- Search Personal Brain for relevant stories/achievements
- Generate compelling answer (maintain authenticity, use user's voice)

**Example:**
```
Q: "Tell us about a time you solved a complex technical problem"

Personal Brain Matching:
→ "Optimized database queries → 10x performance improvement"
→ Technologies: PostgreSQL, indexing, query analysis
→ Context: worked on ChatApp project

Generated Answer:
"While building a real-time chat application, I discovered that 
message queries were taking 2+ seconds. I analyzed query plans, 
added strategic indexes, and implemented pagination. This reduced 
query time to 50ms—a 40x improvement that allowed 10K+ concurrent 
users without slowdown."
```

---

### Tier 3 - Communication & Control (Phase 3)

#### 4.11 WhatsApp/Telegram Control
**What:** Start tasks, answer questions, approve actions from phone
- User sends message to bot: *"Apply to job: [link]"*
- Agent responds with: *"Found role. Analysis shows good fit. Need 3 things: graduation date, visa status, availability. What are your answers?"*
- User responds via chat
- Agent continues and asks for approval before submitting
- Agent sends confirmation + screenshot

**Commands:**
- `apply [link]` → Start application
- `show profile` → Display Personal Brain summary
- `add project [...]` → Quick project addition
- `approve` / `reject` → Approve pending action
- `status` → Current task status

---

#### 4.12 Desktop Agent
**What:** Runs actual browser + local files on user's computer
- Not cloud-only: browser runs on user's machine
- Enables local LLM usage (no API costs, privacy)
- Can access local files, folders, screen
- Sensitive data stays on-device

**Architecture:**
```
Desktop App (Electron/Tauri)
├── Local Browser (Playwright)
├── Local LLM (Ollama/LlamaCpp)
├── Personal Brain DB (SQLite/local)
└── File System Access
```

---

#### 4.13 Privacy Mode
**What:** Keep sensitive data local, use cloud only when appropriate
- **Local processing:** Personal Brain queries, CV generation, local form filling
- **Cloud when needed:** Complex NLP (understanding job descriptions), image understanding (if user allows)
- **User control:** Can toggle privacy mode for individual tasks

**Privacy-First Operations:**
- Personal Brain never leaves device
- CV generation on-device
- Form analysis on-device
- Only send to cloud: job description text (for analysis), screenshots (if explicitly enabled)

---

### Tier 4 - Tracking & Memory (Phase 4)

#### 4.14 Application Tracker
**What:** Complete history of applications and results
```
Application Log Entry:
├── Date Applied
├── Company + Role
├── Job URL
├── Status (Applied, In Progress, Interview, Rejected, Offer)
├── CV Version Used
├── Answers Generated (archived)
├── Screenshots (filled form, confirmation)
├── Application Answers
├── Follow-up Notes
└── Outcome (if known)
```

**Use Cases:**
- Track which companies you've applied to (avoid duplicates)
- See which CV versions got interviews
- Analyze which types of answers perform best
- Build portfolio of your applications

---

#### 4.15 Task Memory & Learning
**What:** Remember workflows and learn from repetition
- Store successful workflows (e.g., LinkedIn job application pattern)
- Learn user's preferences over time
- Speed up repeated tasks
- Suggest improvements based on past attempts

**Learning Examples:**
- First application: Takes 5 minutes (agent asks questions, learns format)
- Second similar application: Takes 2 minutes (reuses learned patterns)
- Application answer that got interview: "Remember this worked well, use similar structure next time"

---

#### 4.16 Error Recovery
**What:** When something fails, analyze and adapt
- Button didn't exist → retry with alternative selector
- Page structure changed → re-analyze with vision
- Form validation error → read error message, ask user for correction
- Network timeout → retry with exponential backoff

**Recovery Strategies:**
1. Detect error (screenshot + compare to expected state)
2. Analyze cause (missing element, different layout, validation error)
3. Try alternative approach
4. If all fail: escalate to user with screenshot + explanation

---

#### 4.17 Activity Timeline
**What:** Show user exactly what agent did, step-by-step
```
Activity Timeline for "Apply to Google UX Role"
├── 14:32:00 - Started task
├── 14:32:05 - Navigated to job posting
├── 14:32:10 - Analyzed job requirements (Vue, React, UX research)
├── 14:32:15 - Checked Personal Brain for relevant projects
├── 14:32:20 - Selected "DesignSystem" project as most relevant
├── 14:32:25 - Generated tailored CV (emphasized UX research)
├── 14:32:30 - Filled form: Name, Email, Phone (auto-filled)
├── 14:32:40 - Asking: "Years of UX research experience?" → User: 3
├── 14:32:50 - Filled "Why Google?" answer
├── 14:33:00 - Ready to submit? → User approved
├── 14:33:05 - Submitted application
├── 14:33:10 - Confirmed success (screenshot attached)
```

---

## 5. Technical Architecture

### 5.1 High-Level System Design

```
┌─────────────────────────────────────────────┐
│           USER INTERFACES                    │
├──────────┬──────────────┬──────────────┬─────┤
│ Chrome   │ WhatsApp/    │   Desktop    │ Web │
│Extension │ Telegram Bot │   Electron   │App  │
└──────────┴──────────────┴──────────────┴─────┘
           │              │              │
           └──────────────┼──────────────┘
                          ↓
        ┌──────────────────────────────┐
        │    TASK ORCHESTRATOR         │
        │ (Parse → Plan → Execute)     │
        └──────────────┬───────────────┘
                       ↓
        ┌──────────────────────────────┐
        │  THREE-LAYER INTELLIGENCE    │
        ├──────────────────────────────┤
        │ 1. Personal Brain (Know You)  │
        │ 2. Task Planner (Know Task)   │
        │ 3. Browser Agent (Know Web)   │
        └──────────────┬───────────────┘
                       ↓
        ┌──────────────────────────────┐
        │  EXECUTION ENGINES           │
        ├──────────────────────────────┤
        │ • Browser Automation         │
        │ • Form Filling               │
        │ • Document Processing        │
        │ • LLM Inference              │
        └──────────────┬───────────────┘
                       ↓
        ┌──────────────────────────────┐
        │  STORAGE LAYER               │
        ├──────────────────────────────┤
        │ • Personal Brain (local DB)  │
        │ • Application Logs           │
        │ • Screenshots + Evidence     │
        │ • Task Memory                │
        └──────────────────────────────┘
```

### 5.2 Core Components

#### Browser Automation Layer
- **Foundation:** Browser Use (Python) or Playwright (Node.js)
- **Responsibility:** Navigate, click, type, screenshot, upload
- **Fallback:** Vision-based understanding when DOM insufficient

#### Personal Brain Service
- **Responsibility:** Store + retrieve user data
- **Storage:** SQLite (local) + optional cloud sync
- **Operations:** Add project, update skills, retrieve for form filling

#### Task Orchestrator
- **Responsibility:** Parse goal → create plan → execute with feedback
- **Pattern:** OODA Loop (Observe → Orient → Decide → Act)
- **Error Handling:** Reflection + self-correction

#### LLM Integration Layer
- **Options:** Local (Llama, Ollama) or Cloud (Claude, GPT-4)
- **Use Cases:** Goal understanding, answer generation, semantic matching
- **Privacy:** Local for Personal Brain queries, cloud for complex analysis

#### Communication Layer
- **Chrome Extension:** Side panel + context menu
- **WhatsApp/Telegram:** Bot commands + natural conversation
- **Desktop:** Electron app with local browser

### 5.3 Data Models

#### Project Model
```python
class Project:
    id: str
    title: str
    description: str
    technologies: List[str]  # ["React", "Node.js", "PostgreSQL"]
    skills_demonstrated: List[str]  # ["fullstack", "system design"]
    github_url: str
    deployment_url: str
    impact: str  # "Processed 1M+ messages daily"
    duration: str  # "Jan 2023 - Dec 2023"
```

#### Experience Model
```python
class Experience:
    id: str
    company: str
    title: str
    start_date: date
    end_date: date
    description: str
    achievements: List[str]
    technologies: List[str]
    skills: List[str]
```

#### Application Model
```python
class Application:
    id: str
    date_applied: datetime
    company: str
    job_title: str
    job_url: str
    status: Enum["Applied", "In Progress", "Interview", "Rejected", "Offer"]
    cv_version: str  # hash of CV used
    answers: Dict[str, str]  # question → answer
    screenshots: List[str]  # paths to evidence
    notes: str
    outcome: str
```

---

## 6. Implementation Phases

### Phase 1: Killer Demo (2-3 weeks)
**Goal:** End-to-end job application on a real job site

**Deliverables:**
- Chrome extension with side panel
- Browser automation (click, type, fill, screenshot)
- Goal parsing ("Apply to this job")
- Simple form filling (hardcoded user data)
- Approval gate before submit
- Screenshot + confirmation

**Success Metric:** Successfully fill and submit application on 1 realistic job site (LinkedIn, Indeed, or similar)

---

### Phase 2: Personal Intelligence (3-4 weeks)
**Goal:** Personal Brain that powers smart filling + tailored CV

**Deliverables:**
- Personal Brain data model + storage
- CV/Resume upload + parsing
- Project + skill storage
- Smart form filling (match fields to Personal Brain)
- Smart project selection (semantic matching)
- Dynamic CV generation (tailored to job)

**Success Metric:** Apply to 5 different jobs with different tailored CVs; reduced user input each time

---

### Phase 3: Communication (2-3 weeks)
**Goal:** Control agent from phone

**Deliverables:**
- WhatsApp/Telegram bot integration
- Task initiation from chat ("Apply to [link]")
- Question asking via chat
- Approval flow via chat
- Screenshot delivery via chat

**Success Metric:** Full application workflow via WhatsApp/Telegram

---

### Phase 4: Polish & Tracking (2-3 weeks)
**Goal:** Production-ready with audit trail

**Deliverables:**
- Application tracker (history, analytics)
- Task memory (learned workflows)
- Error recovery + self-healing
- Activity timeline (explain what agent did)
- Privacy controls

**Success Metric:** User can see complete history, review past applications, understand agent's reasoning

---

## 7. Technical Stack Recommendation

### Backend
- **Language:** Python or Node.js
- **Framework:** FastAPI (Python) or Express (Node.js)
- **Database:** SQLite (local) + PostgreSQL (optional cloud)

### Browser Automation
- **Primary:** Browser Use (Python) or Playwright (Node.js)
- **Execution:** Headless Chrome/Firefox
- **Vision:** Claude Vision API or local model (LLaVA)

### AI/LLM
- **Local Option:** Ollama + Llama 2 (privacy-first)
- **Cloud Option:** Claude API or GPT-4 (more capable)
- **Hybrid:** Use local for Personal Brain, cloud for complex tasks

### UI/Frontend
- **Chrome Extension:** React + Manifest V3
- **Desktop:** Electron + React or Tauri + Vue
- **Web:** React or Vue
- **Bot:** Python-telegram-bot or similar

### Storage
- **Local:** SQLite + file system
- **Cloud (optional):** S3 for screenshots, PostgreSQL for application logs

---

## 8. Security & Privacy Considerations

### Data Security
- Personal Brain encrypted at rest (user's local device)
- Screenshots/documents stored securely
- No credential storage (use browser's password manager)
- Audit log of all actions

### Privacy Guarantees
- Option to run completely locally (no cloud)
- Optional telemetry (opt-in only)
- No tracking of browsing history
- User owns all generated content (CVs, answers)

### Sensitive Action Safety
- Manual approval required before Submit/Send/Pay
- Screenshot review before submission
- Timeout on approval requests (auto-cancel after 1 hour)
- Rollback capability for recent submissions

---

## 8b. Constraints This PRD Originally Ignored

Three constraints surfaced from reading AIHawk and ApplyPilot. Each can sink the product and
none were in the first draft.

### 8b.1 Bot detection is a first-class engineering problem

AIHawk's author abandoned standard Playwright and built
[invisible_playwright](https://github.com/feder-cr/invisible_playwright) — a Firefox patched at
the engine level — specifically because **AIHawk kept getting detected at scale**. Their
documented findings: an attached debugger is itself detectable, CDP-driven automation leaves
fingerprints, and automating a login form is far riskier than reusing an existing session.

Implications:
- Assume LinkedIn/Indeed/Workday actively detect automation. Plan for it in Phase 1, not later.
- **Prefer reusing the user's existing logged-in browser session over automating login.** This
  also removes any need to store the user's password. (Note: ApplyPilot's profile schema has a
  `personal.password` field — we should **not** copy that.)
- Human-paced interaction is both safer and more honest than maximum throughput.
- Detection risk is a reason to favor the user's own browser (Desktop Agent / extension) over
  a datacenter browser.

### 8b.2 Terms of service and account risk

Automated application submission plausibly violates the ToS of LinkedIn, Indeed, and most job
boards. The realistic worst case for a user is **account suspension**, and that is their
primary professional network. This must be disclosed in-product before first run, not buried.

Open question for the team: do we restrict to boards where automation is tolerated, require
the user to acknowledge the risk per-platform, or keep a human in the loop for every submit
(which is our stated design anyway and materially reduces exposure)?

### 8b.3 Volume is a reputational liability

AIHawk drew sustained negative coverage — TechCrunch, Wired, The Verge, 404 Media
("AI is enabling job seekers to think like spammers"; a reporter auto-applied to 2,843 roles).
ApplyPilot leads with "1,000 jobs in 2 days."

That framing invites the same backlash, and it also degrades the thing users actually want:
getting hired. **Haru should explicitly not compete on volume.** Position on quality per
application, human review, and honest representation. Consider a deliberate rate limit as a
product feature rather than a limitation.

---

## 9. Success Metrics

> All numbers below are **aspirational targets set before any build or measurement**. They are
> not forecasts and are not backed by data. Revisit them after Phase 1 produces real numbers.

### Quantitative targets
- **Adoption:** 100+ active users in first month
- **Completion Rate:** 80%+ of initiated applications are successfully completed
- **Time Saved:** Average 10 minutes saved per application
- **Accuracy:** 95%+ form fill accuracy (auto-filled vs. manually entered)

### Qualitative
- User testimonials showing application confidence
- Successful interviews from agent-submitted applications
- User preference for agent over manual application

### Technical
- 99% uptime (for deployed version)
- <2s average task completion time
- Zero data breaches
- <1% error rate in form filling

---

## 10. Open Questions & Future Considerations

1. **Local LLM vs Cloud:** What's the right tradeoff for MVP? Start with cloud (more capable), offer local option later?

2. **Website Coverage:** Should we build site-specific adapters for popular job boards, or keep it universal?

3. **Payment Model:** Freemium (limited applications/month) or subscription?

4. **Scope:** Start with job applications, expand to general form filling?

5. **Integrations:** Should Personal Brain auto-sync with LinkedIn, GitHub, Notion?

---

## 11. Success Stories & Differentiation

### Why Haru Wins
1. **Personal:** Knows who you are, adapts to your style
2. **Intelligent:** Understands opportunities, matches semantically
3. **Trustworthy:** Asks before critical actions, shows proof
4. **Private:** Runs locally, keeps data on your device
5. **Delightful:** WhatsApp/Telegram control, asynchronous interaction

### Honest competitive position
- **vs. Browser Use:** Not just automation, adds intelligence layer
- **vs. Resume Tailor:** Not just CV, does end-to-end applications
- **vs. LinkedIn Easy Apply:** Works on any website, truly tailored
- **vs. Manual applications:** faster, less application fatigue
- **vs. AIHawk:** AIHawk is LinkedIn-only with template resumes. We are broader and per-job tailored.
- **vs. ApplyPilot:** ⚠️ **This is the real competitor and we do not currently beat it.** See below.

### ⚠️ Competitive reality check — ApplyPilot

Section 2 of this PRD originally claimed nobody combines "knows you + knows task + knows web."
That claim is **false as written**. [ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot)
already ships a 6-stage pipeline that discovers jobs across 5 boards plus 48 Workday portals,
scores fit 1–10 against your profile, tailors a resume per job with fabrication validation,
writes cover letters, and autonomously submits via Playwright MCP. It is Python, AGPL-3.0, and
production-grade today.

Where we still have honest room:

| Gap in ApplyPilot | Our opportunity |
| --- | --- |
| CLI-only, no interactive UI | Chrome side panel + real-time approval UX |
| Runs as a batch job | Conversational, one-job-at-a-time, human-in-the-loop |
| No phone control | WhatsApp/Telegram ask-and-approve while away from desk |
| Optimizes for volume (1,000 applications) | Optimize for **quality per application** |
| Profile is a static JSON file | Living Personal Brain: GitHub import, CV parsing, learns over time |
| Job applications only | General web tasks (government forms, downloads, signups) |

**Strategic implication:** our differentiator is **interaction model and breadth**, not the
core pipeline. If we cannot beat ApplyPilot on UX and human-in-the-loop quality, we should
seriously consider contributing to it instead of rebuilding it. AGPL-3.0 means we cannot
copy its code into a closed product — but we can read it, and we should.

---

## Appendix: Inspiration from Related Projects

### Architecture Patterns Borrowed
- **Browser Use:** Core automation architecture
- **REAL Agent:** Orchestrator + Planner + Validator pattern
- **Cognito:** Conversation Agent ↔ Browser Action Agent separation
- **AutoApply.AI:** Workflow (find → analyze → prepare → approve → submit → confirm)
- **ResumeTelling:** Personal Career Brain data structure
- **Resume ArchiTech:** Semantic project matching

### This PRD combines the best of all into one cohesive product that solves a real, painful problem.

---

**Document Version:** 1.0  
**Last Updated:** 2026-08-10  
**Status:** Ready for Engineering Review
