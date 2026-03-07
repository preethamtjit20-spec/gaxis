# G-Axis — AI Browser Agent with Supervised Autonomy

G-Axis is a Chrome Extension + Cloud backend that lets you **talk to your browser**. It sees your screen through Gemini Vision, plans actions, and executes them — while you stay in control through approval gates for risky actions.

**Not a web app. Not a chatbot. A real browser agent.**

## What Makes G-Axis Different

| Feature | Traditional Automation | G-Axis |
|---|---|---|
| Input | Scripts / CSS selectors | Voice + text commands |
| Perception | DOM parsing (fragile) | Gemini Vision (screenshot-based) |
| Execution | Blind clicking | Visual understanding with confidence scoring |
| Safety | None | Policy engine with approval gates |
| Memory | Stateless | Remembers past tasks, learns patterns |
| Architecture | Monolithic script | Agent ecosystem (A2A, MCP, Agent Card) |

## Architecture

```
Chrome Extension (Side Panel + Content Script)
    |
    | WebSocket
    v
Cloud Run Backend (FastAPI + ADK)
    |
    +-- Gemini 2.5 Pro (Vision + Planning)
    +-- Policy Engine (risk scoring, approval gates)
    +-- Memory System (episodic + semantic)
    +-- Audit Store (Firestore)
    +-- Playwright (API mode)
```

### Agent Stack Layers

| Layer | Implementation |
|---|---|
| Agent Client | Chrome Extension (side panel + content script) |
| A2UI | WebSocket event stream -> reactive UI |
| A2A | REST API + Agent Card at `/.well-known/agent.json` |
| Agent Runtime | ADK + Coordinator FSM |
| Tool Access | MCP-compatible browser tools |
| Context/Memory | 3-tier: Working + Episodic + Semantic |
| Infrastructure | Cloud Run + Firestore + Secret Manager |

## Quick Start

### Prerequisites

- Python 3.11+
- Google Chrome
- Gemini API key ([get one here](https://aistudio.google.com/apikey))

### 1. Backend Setup

```bash
# Clone the repo
git clone https://github.com/preethams/gaxis.git
cd gaxis

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
playwright install chromium

# Set your API key
cp .env.example .env
# Edit .env and add your GOOGLE_API_KEY

# Run the server
python run.py
```

The server starts at `http://localhost:8000`. Verify with:
```bash
curl http://localhost:8000/health
# {"status": "ok", "agent": true}
```

### 2. Chrome Extension Setup

1. Open Chrome and go to `chrome://extensions`
2. Enable "Developer mode" (top right)
3. Click "Load unpacked"
4. Select the `extension/` folder from this repo
5. Click the G-Axis icon in your toolbar — the side panel opens
6. Open Settings (gear icon) and set Backend URL to `http://localhost:8000`
7. Click "Test" to verify connection

### 3. Use It

- Type a task: "Search Google for trending AI news"
- Or click the mic button and speak
- Watch the agent analyze the page, plan actions, and execute them
- Approve or deny risky actions when prompted

## Cloud Deployment (Google Cloud)

### Automated (recommended)

```bash
# Set up GCP credentials
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# Create the API key secret
echo -n 'YOUR_GEMINI_API_KEY' | gcloud secrets create gaxis-gemini-key --data-file=-

# Deploy
./deploy.sh YOUR_PROJECT_ID
```

### Terraform (Infrastructure as Code)

```bash
cd terraform
terraform init
terraform apply -var="project_id=YOUR_PROJECT_ID" -var="gemini_api_key=YOUR_KEY"
```

### Update Extension

After deploying, update the Backend URL in extension settings to your Cloud Run URL:
`https://gaxis-XXXXX.run.app`

## API Reference

### REST Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Server health check |
| GET | `/.well-known/agent.json` | Agent Card (A2A discovery) |
| POST | `/api/task` | Start a new task |
| GET | `/api/memory/{domain}` | Get episodic memory for a domain |
| GET | `/api/patterns` | Get semantic patterns |

### WebSocket (`/ws`)

Send JSON messages:

```json
{"type": "run_task", "instruction": "Search for flights to Tokyo", "mode": "extension"}
{"type": "approve"}
{"type": "deny"}
{"type": "screenshot", "screenshot": "<base64>", "url": "...", "title": "..."}
```

Receive events:

```json
{"type": "task_started", "task_id": "task_abc123", "data": {...}}
{"type": "perception", "task_id": "...", "data": {"page_summary": "...", "elements": [...]}}
{"type": "action_planned", "task_id": "...", "data": {"action_type": "click", "x": 640, "y": 360, ...}}
{"type": "approval_needed", "task_id": "...", "data": {"risk_level": "high", "reason": "..."}}
{"type": "task_completed", "task_id": "...", "data": {"summary": "..."}}
```

## Memory System

G-Axis remembers across sessions:

- **Episodic Memory**: Per-domain task history. "Last time on Google Flights, the date picker needed a double click."
- **Semantic Memory**: Cross-site patterns. "Cookie banners usually have an 'Accept All' button."
- **Working Memory**: Current task state (dies with the task).

5 built-in patterns ship with G-Axis (cookie consent, search inputs, login flows, pagination, popup close).

## Safety & Supervision

Three supervision modes:
- **Supervised**: Approve all risky actions (default)
- **Semi-automatic**: Only approve critical actions (passwords, payments)
- **Autonomous**: No approvals (use with caution)

The policy engine evaluates every action for:
- Risk level (none / low / medium / high / critical)
- Confidence score (below threshold = require approval)
- Cumulative risk (many low-risk actions in sequence = escalate)
- Sensitive field detection (password, payment, PII)

## Tech Stack

| Component | Technology |
|---|---|
| AI Model | Gemini 2.5 Pro (vision + planning) |
| Agent Framework | Google ADK |
| Backend | Python + FastAPI + WebSocket |
| Browser Control | Playwright |
| Extension | Chrome Manifest V3 |
| Database | Google Cloud Firestore |
| Deployment | Google Cloud Run |
| IaC | Terraform |

## Project Structure

```
gaxis/
├── backend/
│   ├── agent/core.py          # Agent coordinator with dual-mode execution
│   ├── vision/perception.py   # Gemini Vision screenshot analysis
│   ├── browser/runtime.py     # Playwright browser control
│   ├── policy/engine.py       # Risk scoring + approval gates
│   ├── memory/store.py        # 3-tier memory system
│   ├── audit/store.py         # Firestore audit logging
│   └── main.py                # FastAPI server + WebSocket + A2A
├── extension/
│   ├── manifest.json           # Chrome MV3 manifest
│   ├── background/             # Service worker (WS hub)
│   ├── sidepanel/              # Side panel UI
│   ├── content/                # Page overlays + action execution
│   ├── options/                # Settings page
│   └── shared/                 # Shared types
├── terraform/main.tf           # GCP infrastructure as code
├── deploy.sh                   # One-command Cloud Run deployment
├── Dockerfile                  # Cloud Run container
└── pyproject.toml              # Python dependencies
```

## License

MIT

---

Built for the [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/) #GeminiLiveAgentChallenge
