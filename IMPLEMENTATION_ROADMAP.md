# Haru Implementation Roadmap
## Detailed Technical Plan & Phase Breakdown

---

## 1. Technical Stack Decision Matrix

Based on Browser Use analysis and project requirements, here are the recommended decisions:

### 1.1 Core Browser Automation

**Decision: Python + Browser Use + Playwright Hybrid**

```
Layer                    Technology          Why
─────────────────────────────────────────────────────────
Browser Control          Playwright          - Direct CDP access
                         (Python)            - Reliable automation
                                             - Type-safe actions

High-Level Agent         Browser Use         - Battle-tested
                         (Python)            - Vision + DOM fallback
                                             - Recovery mechanisms
                                             - Orchestrator pattern

Orchestration            Custom Python       - REAL Agent pattern
                         (Orchestrator)      - Separation of concerns
```

**Why this stack:**
- Browser Use provides proven automation + recovery patterns
- Playwright gives low-level control when needed
- Python ecosystem for AI/NLP is more mature (spaCy, transformers)
- Easier local LLM integration (ollama, LlamaCpp)

**Execution model: deterministic first, agent only on failure.**
Verified from [workflow-use](https://github.com/browser-use/workflow-use), which has a dedicated
`healing/` module and selector-generator/xpath-optimization logic in its controller. Do **not**
let an LLM improvise every step on every run — it is slow, expensive, and non-reproducible.

```
Known site (e.g. Greenhouse, Workday, Lever)
        ↓
Replay recorded deterministic workflow   ← fast, free, reproducible
        ↓
   step fails?
        ↓ yes
Fall back to LLM browser agent for that step
        ↓
Succeeded? → heal the stored workflow so next run is deterministic again
```

Two consequences: the 10th Workday application costs near-zero LLM tokens, and each failure
makes the system permanently better. This should be designed into Phase 1's action layer even
though healing itself lands in Phase 4.

**Session strategy (security-critical):** attach to the user's existing logged-in browser
profile. Do not automate login and do not store passwords — see PRD §8b.1.

---

### 1.2 Backend Architecture

```
Backend Service (FastAPI)
├── REST API Endpoints
│   ├── /task/create (start new task)
│   ├── /task/{id}/status (poll status)
│   ├── /task/{id}/approve (human approval)
│   └── /task/{id}/screenshot (get evidence)
├── WebSocket Server
│   ├── Real-time progress updates
│   ├── Human-in-the-loop questions
│   └── Approval gates
└── Background Workers (Celery)
    ├── Task Orchestrator
    ├── Form Analyzer
    ├── CV Generator
    └── Answer Generator
```

**Tech Stack:**
- **Framework:** FastAPI (async, type-hints, auto-docs)
- **Job Queue:** Celery + Redis (task distribution)
- **DB:** SQLite (local) + PostgreSQL (optional cloud)
- **Cache:** Redis (session state, embeddings cache)

---

### 1.3 Personal Brain Architecture

```
Personal Brain Service
├── Data Layer (SQLite)
│   ├── Projects table
│   ├── Experience table
│   ├── Skills table
│   └── Documents table
├── Processing Layer
│   ├── Document parser (PDFs, images)
│   ├── Information extractor (LLM-based)
│   └── Embedding generator (semantic search)
└── Query Layer
    ├── Form field matcher
    ├── Project selector
    └── Skill ranker
```

**Key Feature: Semantic Search**
```python
# When matching form field "Tell us about your backend experience"
# to user's Personal Brain:

user_experiences = [
    {"role": "Backend Engineer", "skills": ["Python", "PostgreSQL", "microservices"]},
    {"role": "DevOps", "skills": ["Kubernetes", "CI/CD", "infrastructure"]},
]

# Embed the form field question
field_embedding = embed("Tell us about your backend experience")

# Find most relevant experience
best_match = find_most_relevant(user_experiences, field_embedding)
# → Backend Engineer experience (highest semantic similarity)
```

---

### 1.4 LLM Strategy

**Decision: Hybrid Local + Cloud**

```
Use Case                    Provider            Reason
──────────────────────────────────────────────────────
Goal parsing               Local (Ollama)       Fast, always available
Form field analysis        Local or Cloud       Trade speed vs accuracy
CV generation              Local (Llama 2)      Privacy-critical
Answer generation          Cloud (Claude)       Complex reasoning needed
Project matching           Local (embeddings)   Speed + privacy
Job requirement parsing    Cloud (Claude)       Accuracy matters
```

**Implementation Pattern:**
```python
class LLMRouter:
    async def generate_cv(self, user_data, job_desc):
        # Privacy-critical: run local
        return await local_llm.generate(...)
    
    async def generate_answer(self, question, user_context):
        # Complex: use cloud for quality
        return await claude.generate(...)
    
    async def parse_form(self, form_html):
        # Speed matters: use local
        return await local_llm.parse(...)
```

---

## 2. Phase 1: Killer Demo (2-3 weeks)

### Goal
End-to-end job application on a real job board (LinkedIn Easy Apply or Indeed)

### Deliverables

#### 2.1 Chrome Extension Skeleton
**Files:**
- `manifest.json` - Extension configuration
- `side-panel/panel.html` - Main UI
- `side-panel/panel.js` - Panel controller
- `content-script.js` - Page interaction
- `background-service-worker.js` - Event handling

**Features:**
- Side panel UI with task input
- "Apply to this job" button (context menu)
- Progress indicator
- Screenshot viewer
- Approval modal

**Code Sketch:**
```javascript
// background-service-worker.js
chrome.runtime.onMessage.addListener(async (request, sender) => {
    if (request.action === "startTask") {
        const task = await backend.createTask({
            goal: request.goal,
            url: sender.url
        });
        // Poll for updates
        broadcastProgress(task);
    }
});

// side-panel/panel.js
document.getElementById("applyBtn").addEventListener("click", () => {
    const goal = "Apply to this job";
    chrome.runtime.sendMessage({ action: "startTask", goal });
});
```

#### 2.2 FastAPI Backend

**Endpoints:**
```python
# app/main.py
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.post("/task/create")
async def create_task(task_req: TaskRequest) -> TaskResponse:
    """Start new task"""
    task = Task.create(goal=task_req.goal, url=task_req.url)
    celery_app.send_task("orchestrator.run", args=[task.id])
    return TaskResponse(id=task.id, status="queued")

@app.get("/task/{task_id}/status")
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """Poll task progress"""
    task = Task.get(task_id)
    return TaskStatusResponse(
        status=task.status,
        current_step=task.current_step,
        screenshot=task.latest_screenshot
    )

@app.post("/task/{task_id}/approve")
async def approve_task(task_id: str, approval: ApprovalRequest):
    """User approves submission"""
    task = Task.get(task_id)
    task.approved = True
    task.save()
    return {"status": "approved"}

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """Real-time updates for UI"""
    await websocket.accept()
    async for update in task.stream_updates():
        await websocket.send_json(update)
```

#### 2.3 Browser Orchestrator

**Architecture:**
```python
# orchestrator/service.py

class TaskOrchestrator:
    """Main OODA loop: Observe → Orient → Decide → Act"""
    
    async def run(self, task_id: str):
        task = Task.get(task_id)
        
        # Phase 1: Analyze
        analyzer = JobAnalyzer()
        form_data = await analyzer.analyze_page(task.url)
        
        # Phase 2: Decide
        planner = FormPlanner()
        plan = planner.create_plan(form_data)
        
        # Phase 3: Execute
        browser = BrowserSession()
        await browser.navigate(task.url)
        
        for step in plan:
            result = await self.execute_step(browser, step)
            if not result.success:
                # Reflect and retry
                new_step = await self.reflect_and_retry(
                    browser, step, result.error
                )
                result = await self.execute_step(browser, new_step)
            
            task.add_action(result)
            task.update_screenshot(await browser.screenshot())
        
        # Phase 4: Await Approval
        task.status = "awaiting_approval"
        task.save()
        
        # Wait for user approval
        while not task.approved:
            await asyncio.sleep(1)
        
        # Phase 5: Submit
        await browser.submit()
        task.status = "completed"
        task.save()

class FormPlanner:
    """Convert form analysis → execution plan"""
    
    def create_plan(self, form_data: FormAnalysis) -> List[Action]:
        """
        form_data = {
            "fields": [
                {"name": "Full Name", "type": "text", "required": True},
                {"name": "Email", "type": "email", "required": True},
                {"name": "Cover Letter", "type": "textarea", "required": False},
                {"name": "Submit", "type": "button"}
            ]
        }
        
        Output:
        [
            Action(type="fill", field="Full Name", value="Alice Chen"),
            Action(type="fill", field="Email", value="alice@example.com"),
            Action(type="ask_user", field="Cover Letter", 
                   question="Would you like to add a cover letter?"),
            Action(type="click", target="Submit")
        ]
        """
        plan = []
        
        for field in form_data["fields"]:
            if field["type"] == "button":
                plan.append(Action(type="click", target=field["name"]))
            elif field["required"]:
                plan.append(Action(
                    type="fill",
                    field=field["name"],
                    value=self.get_default_value(field)
                ))
            else:
                plan.append(Action(
                    type="ask_user",
                    field=field["name"],
                    question=f"Should we fill '{field['name']}'?"
                ))
        
        return plan
```

#### 2.4 Hardcoded User Data (MVP)

**For Phase 1, hardcode a user profile:**
```python
# data/user_profile.py

USER_DATA = {
    "full_name": "Alice Chen",
    "email": "alice@example.com",
    "phone": "+1-555-0123",
    "location": "San Francisco, CA",
    "experience": [
        {
            "role": "Software Engineer",
            "company": "Acme Corp",
            "years": "2021-2023",
            "description": "Built backend services..."
        }
    ],
    "skills": ["Python", "React", "PostgreSQL"],
    "education": {
        "school": "UC Berkeley",
        "degree": "BS Computer Science",
        "graduation": "2021"
    }
}
```

#### 2.5 Simple Form Filling

**Matching algorithm for Phase 1:**
```python
# form_filling/matcher.py

class FieldMatcher:
    """Simple regex-based field matching"""
    
    FIELD_PATTERNS = {
        "full_name": ["name", "full name", "your name"],
        "email": ["email", "email address"],
        "phone": ["phone", "phone number", "contact number"],
        "location": ["location", "city", "address"],
    }
    
    def match_field(self, form_field_label: str) -> Optional[str]:
        """Match form field to user data field"""
        label_lower = form_field_label.lower()
        
        for user_field, patterns in self.FIELD_PATTERNS.items():
            for pattern in patterns:
                if pattern in label_lower:
                    return user_field
        
        return None
    
    def get_value(self, field_name: str) -> str:
        """Get value from USER_DATA"""
        return USER_DATA.get(field_name, "")
```

**Phase 2 enhancement:** Replace with semantic matching using embeddings.

---

### 2.6 Phase 1 Technical Checklist

**Backend:**
- [ ] FastAPI service with /task endpoints
- [ ] Celery task queue for async operations
- [ ] TaskOrchestrator OODA loop
- [ ] FormAnalyzer DOM parser
- [ ] FormPlanner step generator
- [ ] Playwright browser control
- [ ] Screenshot capture after each action
- [ ] Simple field matcher (regex-based)

**Chrome Extension:**
- [ ] Side panel UI (HTML/CSS/JS)
- [ ] "Apply to this job" context menu
- [ ] Task status polling
- [ ] Screenshot viewer
- [ ] Approval modal with "Yes/No/Review"
- [ ] Progress indicator
- [ ] Communication with backend

**Database:**
- [ ] Task table (id, status, url, created_at, approved_at)
- [ ] Action table (id, task_id, type, field, value, screenshot)
- [ ] User profile table (hardcoded for Phase 1)

**Integration Tests:**
- [ ] End-to-end test on staging job board
- [ ] Form filling accuracy test
- [ ] Approval flow test
- [ ] Screenshot capture test

**Success Criteria (none of these have been attempted yet):**
- [ ] Can fill and submit job application on LinkedIn/Indeed
- [ ] User gets screenshot before approval
- [ ] Activity timeline shows all steps
- [ ] Recovery works if page structure changes mid-task

---

## 3. Phase 2 Preview: Personal Brain (3-4 weeks)

### High-Level Changes

**What's New:**
- Personal Brain data model + storage
- CV/Resume parsing + upload
- Smart form filling (semantic matching instead of regex)
- Smart project selection (based on job requirements)
- Dynamic CV generation

**New Files:**
```
app/
├── personal_brain/
│   ├── models.py (Project, Experience, Skill, Document)
│   ├── service.py (CRUD operations)
│   ├── parser.py (Parse CV/resume PDF → structured data)
│   └── semantic_search.py (Embeddings + similarity search)
├── cv_generator/
│   ├── templates.py (CV templates/formats)
│   ├── generator.py (Generate tailored CV)
│   └── style_preserver.py (Maintain user's formatting)
└── project_selector/
    ├── matcher.py (Semantic project-job matching)
    └── ranker.py (Rank projects by relevance)
```

**API Changes:**
```python
@app.post("/brain/projects")
async def add_project(project: ProjectInput):
    """Add project to Personal Brain"""
    
@app.post("/brain/upload-cv")
async def upload_cv(file: UploadFile):
    """Parse CV and populate Personal Brain"""
    
@app.get("/cv/generate")
async def generate_cv(job_description: str) -> bytes:
    """Generate tailored CV for job"""
    
@app.post("/answer/generate")
async def generate_answer(question: str, context: str) -> str:
    """Generate application answer"""
```

---

## 4. Repository Structure

```
haru/
├── backend/
│   ├── app/
│   │   ├── main.py (FastAPI app)
│   │   ├── models.py (SQLAlchemy models)
│   │   ├── schemas.py (Pydantic models)
│   │   ├── orchestrator/
│   │   │   ├── service.py
│   │   │   ├── planner.py
│   │   │   └── executor.py
│   │   ├── browser/
│   │   │   ├── session.py
│   │   │   ├── tools.py
│   │   │   └── recovery.py
│   │   ├── form_filling/
│   │   │   ├── analyzer.py
│   │   │   └── matcher.py
│   │   ├── personal_brain/ (Phase 2)
│   │   ├── cv_generator/ (Phase 2)
│   │   └── project_selector/ (Phase 2)
│   ├── tests/
│   │   ├── test_orchestrator.py
│   │   ├── test_form_filling.py
│   │   └── test_e2e.py
│   ├── requirements.txt
│   ├── .env.example
│   └── docker-compose.yml
├── extension/
│   ├── manifest.json
│   ├── side-panel/
│   │   ├── panel.html
│   │   ├── panel.css
│   │   └── panel.js
│   ├── content-script.js
│   ├── background-service-worker.js
│   └── assets/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SETUP.md
│   └── API.md
├── PRD.md
└── IMPLEMENTATION_ROADMAP.md (this file)
```

---

## 5. Development Setup

### 5.1 Backend Setup

```bash
# Clone repo
git clone <repo>
cd haru/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Set up .env
cp .env.example .env
# Edit .env with your settings (OpenAI key, etc.)

# Start services
docker-compose up -d redis postgres

# Run migrations
alembic upgrade head

# Start FastAPI server
uvicorn app.main:app --reload

# In another terminal, start Celery worker
celery -A app.tasks worker --loglevel=info
```

### 5.2 Extension Setup

```bash
cd haru/extension

# Install dependencies
npm install

# Build extension
npm run build

# Load unpacked extension
# Chrome: Settings → Extensions → Load unpacked → select `haru/extension/dist`
```

### 5.3 Testing

```bash
# Run backend tests
pytest tests/ -v

# Run integration test (needs staging job board account)
pytest tests/test_e2e.py -v

# Test form filling on real website
python -m pytest tests/test_form_filling.py::test_linkedin_application -v
```

---

## 6. Risk Mitigation

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| **Bot detection blocks us** | **High** | **Critical** | Reuse user's logged-in session, never automate login, human pacing, run in user's own browser. See PRD §8b.1 |
| **ToS violation → user account ban** | **Medium** | **Critical** | Disclose before first run, human approval on every submit, per-platform acknowledgement. See PRD §8b.2 |
| **LLM fabricates on a resume** | **High** | **Critical** | Fact-boundary validator before any content reaches a form. See PRD §4.7b |
| **ApplyPilot already does this** | **Certain** | **High** | Differentiate on UX/human-in-loop/breadth, or contribute upstream. See PRD §11 |
| Form structure varies by website | High | High | DOM + vision fallback, test on 3+ sites |
| Browser session crashes | Medium | High | Watchdog pattern from Browser Use, auto-recovery |
| LLM costs (cloud API) | Medium | Medium | Use local LLM for MVP, add cost controls |
| Data privacy (Personal Brain) | Low | High | Encrypt local storage, never send to cloud |
| Approval gate UX friction | High | Medium | WebSocket real-time updates, clear screenshots |

### Mitigation Strategies

1. **Form Variation:** Implement hybrid DOM + vision detection
2. **Browser Crashes:** Use Browser Use's watchdog pattern + circuit breakers
3. **LLM Costs:** Start with local Ollama, add cloud option later
4. **Privacy:** Encrypt Personal Brain DB, add opt-in cloud sync only
5. **UX:** Real-time WebSocket updates, show before/after screenshots

---

## 7. Success Metrics for Phase 1

> These are **targets to aim at**, not measurements. Nothing has been built or measured yet.
> The thresholds below are guesses and should be re-set to something defensible once we have
> a first run against a real job board.

### Quantitative targets
- Form fill accuracy: > 90% (hardcoded + simple matching)
- Task completion rate: > 80% (successful applications submitted)
- Time to complete: < 2 minutes per application
- Browser crash recovery: > 95% success rate
- Test coverage: > 70% (backend)

### Qualitative targets
- Approval UX is frictionless
- Screenshots clearly show what was filled
- Error messages are helpful
- Extension UI is intuitive

---

## 8. Transition to Phase 2

**Prerequisites for Phase 2:**
- Phase 1 is stable and tested
- Team has experience with codebase
- Personal Brain data model designed
- LLM integration strategy confirmed

**Phase 2 Kickoff Checklist:**
- [ ] Review Phase 1 metrics
- [ ] Refactor Form Planner for semantic matching
- [ ] Build Personal Brain service
- [ ] Add CV template system
- [ ] Implement embedding-based project matching
- [ ] Design Personal Brain upload/management UI

---

## Appendix: Dependencies

> **Unverified.** The version numbers below were written from memory and have **not** been
> checked against PyPI/npm. Resolve real versions with `pip index` / `npm view` before pinning.
> Treat this as a package list, not a lockfile.

### Backend (packages, versions TBD)
```
fastapi
celery
redis
sqlalchemy
pydantic
playwright
browser-use
ollama          # local LLM
anthropic       # cloud LLM (optional)
pdf2image       # CV parsing
pytesseract     # OCR
chromadb        # vector embeddings
pytest
pytest-asyncio
```

### Extension (packages, versions TBD)
```
react
typescript
webpack
tailwindcss
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-08-10  
**Status:** Ready for Engineering Sprint Planning
