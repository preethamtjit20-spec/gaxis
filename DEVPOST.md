# G-Axis

## Inspiration

I kept catching myself with six tabs open just to plan one meeting. ChatGPT in one tab, Calendar in another, three Google searches running. Every AI tool lives in its own world, completely disconnected from where I actually do my work: the browser.

So I started thinking, what if the browser itself could think? Not some new app I have to download. Not another chatbot in another tab. Something that just lives inside Chrome, sees what I see, and can actually do things when I ask.

When the Gemini Live Agent Challenge dropped, it clicked. Gemini's Live API does something nobody else does: real time, two way voice. Not text to speech. Actual conversation. I wanted to build something that feels like having a smart friend sitting next to you while you work.

## What it does

G-Axis is a Chrome extension that does two things really well.

**First, it talks.** Click the mic and just start speaking. G-Axis connects straight to Gemini's Live API for real time voice. I built 8 different AI personas: Friendly Buddy, Wise Mentor, Creative Partner, Chill Companion, Professional Coach, Job Interviewer, Friendly Debater, and Storyteller. Each one has its own voice and personality. You can switch between them mid conversation and it feels seamless.

It also searches the web while you talk. Ask "what's happening in AI this week?" and it actually goes and looks it up, giving you current data, not something from training.

After every conversation, Gemini analyzes how you communicated across five dimensions: Confidence, Clarity, Engagement, Listening, and Pacing. You earn XP, level up, and track streaks on a dashboard. It turns casual voice chat into something that actually helps you grow.

**Second, it acts.** Type "plan a 5 day Japan itinerary" and watch it go. It opens tabs, researches across multiple sites, pulls everything together, and hands you a full document. Type "schedule a meeting tomorrow at 10am" and it opens Calendar, fills in the details, and saves the event. It sees pages through Gemini Vision and always asks before doing anything risky.

## How I built it

Built this one solo.

### Technical Specifications

**System Architecture**

| Layer | Technology | Role |
|-------|-----------|------|
| Client | Chrome Extension (Manifest V3) | Side Panel UI, Service Worker, Content Script |
| Voice Engine | Gemini Live API via direct WebSocket | Bidirectional native audio streaming |
| Task Engine | Gemini 2.5 Flash via REST | Planning, function calling, analysis |
| Perception | Gemini Vision | Screenshot based UI understanding |
| Search | Google Search (Grounding) | Real time web data in voice sessions |
| Memory | text-embedding-004 | Cosine similarity retrieval over episodic store |
| Backend | Python 3.12 / FastAPI / Uvicorn | Multi agent orchestration, WebSocket server |
| Hosting | Google Cloud Run | 2 vCPU, 2GB RAM, autoscale 1 to 3 instances |
| Secrets | Google Cloud Secret Manager | API key storage, OAuth2 token generation |
| CI/CD | Google Cloud Build | Docker image build and push to GCR |
| IaC | Terraform | Cloud Run, Secret Manager, IAM, Cloud Scheduler |
| Scheduling | Cloud Scheduler | Daily analysis (00:00 UTC), weekly reports (Sun 23:00 UTC) |

**Voice Pipeline Specifications**

| Component | Specification |
|-----------|--------------|
| Mic Capture | AudioWorkletNode, PCM Int16, 16kHz mono, 4096 sample buffer |
| Transport (up) | chrome.runtime.Port from popup to Service Worker |
| Gemini Connection | Direct WebSocket to `wss://generativelanguage.googleapis.com/ws/...BidiGenerateContent` |
| Model | `gemini-2.5-flash-native-audio-preview-12-2025` |
| Audio Output | PCM Int16, 24kHz mono, base64 encoded |
| Playback | Web Audio API, scheduled `AudioBufferSource.start(preciseTime)`, gapless |
| Reconnection | Transparent, up to 20 reconnects on session timeout (~10 min) |
| Latency | Zero hop (extension to Gemini direct, no backend proxy) |

**Persona Configuration**

| Persona | Voice | System Prompt Style |
|---------|-------|-------------------|
| Friendly Buddy | Puck | Warm, casual, curious |
| Wise Mentor | Charon | Calm, insightful, Socratic |
| Creative Partner | Aoede | Energetic, divergent, "yes and" |
| Chill Companion | Fenrir | Relaxed, low pressure, easy going |
| Professional Coach | Kore | Structured, direct, actionable |
| Job Interviewer | Kore | Behavioral questions, feedback after each answer |
| Friendly Debater | Charon | Respectful opposition, evidence based |
| Storyteller | Aoede | Vivid, dramatic, collaborative narrative |

**Browser Automation Architecture**

| Component | Implementation |
|-----------|---------------|
| Orchestrator | `GAxisAgent` (core.py) delegates to specialist agents |
| Fast Loop | `FastAgentLoop` (fast_loop.py) one Gemini call per action step |
| Planner | Conversational task decomposition before execution |
| Researcher | `ResearchLoop` (research_loop.py) multi source web scanning, .docx generation |
| Tool Executor | 12 tools: click, type_text, navigate, scroll, press_key, hover, fill_form, extract_data, wait, rollback, task_complete, task_failed |
| Content Script | DOM snapshot, MutationObserver, blocker detection, visual overlay, action execution |
| Policy Engine | Risk scoring (none/low/medium/high/critical), cumulative risk tracking, sensitive field detection (password, payment, PII), approval gates |
| UI Graphs | Semantic node/edge models for Calendar, Gmail, Docs, Sheets, Meet enabling deterministic form filling |
| Connectors | 9 services, 34 skills: Calendar (6), Gmail (4), Drive (3), Docs (3), Sheets (3), Meet (3), YouTube (2), General (7), Research (3) |
| Memory | 3 tier: Working (per task), Episodic (per domain), Semantic (cross site patterns, 5 built in) |

**Conversation Analytics**

| Metric | Details |
|--------|---------|
| Skills Tracked | Confidence, Clarity, Engagement, Listening, Pacing (0 to 100 each) |
| Analysis Model | Gemini 2.5 Flash with structured JSON output |
| XP System | 10 XP per minute + 50 XP per session + skill bonus, 500 XP per level |
| Streak | Daily tracking, current and longest streak |
| Session Record | Persona, duration, message count, word counts, topics, intent, summary, action items |

**Security Architecture**

| Concern | Implementation |
|---------|---------------|
| API Key Storage | Google Cloud Secret Manager (`gaxis-gemini-key`) |
| Runtime Auth | OAuth2 access token via `google.auth.default()`, 60 min expiry |
| Token Delivery | `GET /api/v` returns token, extension uses it for Gemini WSS |
| Key in Code | Never. Scrubbed from git history via `filter-branch` |
| CORS | `allow_origins=["*"]`, `allow_credentials=False` |
| Path Traversal | `Path.resolve().is_relative_to()` validation on file endpoints |
| Sensitive Actions | Policy engine requires approval for login, payment, OAuth pages |

**Deployment Pipeline**

```
deploy.sh
  1. gcloud services enable (run, cloudbuild, secretmanager)
  2. gcloud secrets create gaxis-gemini-key
  3. gcloud secrets add-iam-policy-binding (service account access)
  4. gcloud builds submit (Docker build, push to GCR)
  5. gcloud run deploy (image, env vars, secrets, scaling)

terraform/main.tf
  Resources: project_service (5 APIs), secret_manager_secret,
             cloud_run_v2_service, service_iam_member,
             cloud_scheduler_job (daily + weekly)
```

### How the voice pipeline works

This was the hardest part to get right. Chrome sidepanels can't access the microphone directly, so I had to build a workaround. A tiny popup window opens, requests mic permission, captures audio through an AudioWorklet at 16kHz, and streams it through Chrome ports to the service worker. The service worker connects directly to Gemini Live over WebSocket. No backend in the middle. Audio comes back at 24kHz and plays through a scheduler I built that times each buffer to start at the exact moment the previous one ends. No gaps, no stuttering.

### How personas work

Each of the 8 personas lives in a single JS file with its own system prompt, voice selection, and conversation style. When you switch mid conversation, the current session gets saved and analyzed automatically, the transcript clears, and a fresh connection opens with the new persona's config.

### How browser automation works

The backend runs a multi agent system. An orchestrator hands tasks to a fast loop (one Gemini call per step), a planner (for complex multi step goals), or a researcher (scans multiple websites). Twelve browser tools handle the actual clicking, typing, scrolling, and form filling through the content script. A policy engine checks every action for risk and asks for your approval on anything sensitive.

### How security works

The API key sits in Cloud Secret Manager. When the extension needs to start a voice session, it hits a backend endpoint that generates a short lived OAuth2 token (good for about 60 minutes). The actual key never touches the extension code, never shows up in git, never crosses the network as a raw credential.

### How deployment works

One script does everything. Run `./deploy.sh` and it enables the APIs, creates the secrets, builds the Docker image through Cloud Build, and deploys to Cloud Run. Terraform manages all the resources. I can tear down and rebuild the entire infrastructure in minutes.

## Challenges I ran into

**The mic permission nightmare.** Spent over 6 hours on this. Chrome sidepanels can't show the browser's permission dialog. Offscreen documents can't either. I tried four completely different approaches before landing on the popup window method that finally worked.

**Sessions dying after one response.** This one was subtle. I had built voice activity detection on the client side to avoid sending silence. Turns out Gemini needs that continuous audio stream to know the session is still alive. The moment I stopped sending silence, Gemini thought I disconnected and killed the session. Removing my own VAD and letting Gemini handle silence detection fixed it instantly.

**The 1008 crashes.** Every time the voice model tried to call a browser tool (click, navigate, etc.), the whole session crashed with a policy violation error. Took me 3 hours to figure out that the native audio model simply doesn't support custom function calling. I had to split everything: voice runs client side with just Google Search, browser automation runs server side with the full tool set.

**Choppy audio.** Words were getting cut off, speech sounded robotic. The issue was tiny gaps between audio chunks because I was waiting for each one to finish before starting the next. Switching to pre scheduled playback where each chunk is timed to start at the exact millisecond the previous one ends made everything smooth.

**10 minute timeout.** Gemini Live sessions just die after about 10 minutes. I built auto reconnection that handles this transparently. The user sees a quick "extending session" message and the conversation continues. Supports up to 20 reconnections so conversations can go for hours.

**The API key incident.** I accidentally committed my Gemini key to the public repo. Had to scrub it from the entire git history with filter branch, rotate the key, and rebuild the whole auth flow around OAuth tokens. Learned that lesson the hard way.

**Localhost URLs in production.** After deploying to Cloud Run, document downloads were still pointing to localhost:8000. Tracked down hardcoded URLs in three different files. Changed everything to relative paths that resolve against the backend URL from settings.

**Service worker won't load.** Adding an await inside the message handler broke the service worker completely. Chrome's MV3 is strict about module syntax. Wrapped the handler in an async function and it worked.

**CORS blocking everything.** Tightened CORS to chrome-extension://* and it broke because that's not a valid pattern. Chrome extensions don't send standard Origin headers from service worker fetch calls.

**Files disappearing on Cloud Run.** Generated documents would vanish between requests because containers are ephemeral. Set minimum instances to 1 so at least one container stays warm.

## Accomplishments that I'm proud of

The voice feels genuinely real time. There's no noticeable delay between speaking and getting a response because the WebSocket goes directly from the extension to Gemini with nothing in between.

Switching personas mid conversation and hearing a completely different voice and personality respond is honestly fun. Going from a casual buddy to a sharp job interviewer in one click and having the previous session automatically analyzed makes the whole thing feel polished.

The analytics dashboard surprised me. Watching your communication skills get scored after every conversation and seeing your XP grow turns what could be a gimmick into something genuinely useful.

Getting the entire cloud deployment down to one command felt great. And knowing the API key is properly secured through OAuth tokens instead of hardcoded anywhere gives me confidence to share the repo publicly.

## What I learned

Gemini's Live API works best when you stop fighting it. It handles voice detection, turn taking, and interruptions on its own. Every time I tried to add my own logic on top (like client side silence filtering), things broke. Working with its design instead of against it made everything smoother.

Chrome extensions in MV3 have real limitations that aren't obvious until you hit them. Service workers can't show dialogs, sidepanels can't access the mic, offscreen documents have restrictions. Building something voice powered in this environment requires a lot of creative problem solving.

The difference between bad audio and good audio is tiny in the code but enormous in the experience. One line change from callback based playback to scheduled playback transformed the entire feel of the voice feature.

Personas are simple to build but completely change how the product feels. A generic AI sounds like a tool. A "Friendly Buddy" with a warm voice sounds like a friend. The technical complexity is minimal but the user impact is massive.

Security is something you learn by making mistakes. I went through five iterations of how to handle the API key, each one triggered by discovering a real vulnerability.

## What's next for G-Axis

Moving conversation storage to Firebase so data persists across devices and supports multiple users.

Building weekly AI generated progress reports that analyze your conversations and set goals.

Adding group conversation scenarios where multiple personas interact in a simulated team meeting or panel interview.

Bringing browser actions back into voice with a confirmation step so you can say "open my calendar" and the agent asks before acting.

A mobile companion app that connects to the same backend for practice on the go.

And eventually letting users create and share their own custom personas with the community.

## Try it

Live backend: https://gaxis-132388856648.us-central1.run.app/health

GitHub: https://github.com/preethamtjit20-spec/gaxis

Agent Card: https://gaxis-132388856648.us-central1.run.app/.well-known/agent.json

Built for the Gemini Live Agent Challenge. Your browser already works. G-Axis makes it intelligent.
