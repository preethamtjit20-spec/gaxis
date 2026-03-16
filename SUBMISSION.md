# G-Axis — Submission Details

## Project Name
**G-Axis**

## Elevator Pitch
**Your browser already works. G-Axis makes it intelligent.** A Chrome extension that combines real-time voice AI companions with autonomous browser automation — powered by Gemini Live API.

## What it does
G-Axis is a Chrome extension that turns any browser into an AI-powered workspace. It has two core capabilities:

1. **Voice AI Companion** — Real-time voice conversations via Gemini Live API with 8 distinct AI personas (Friendly Buddy, Wise Mentor, Creative Partner, Chill Companion, Professional Coach, Job Interviewer, Friendly Debater, Storyteller). Each persona has its own voice, personality, and conversation style. Conversations are analyzed for communication skills (Confidence, Clarity, Engagement, Listening, Pacing) with XP, leveling, and streak tracking.

2. **Autonomous Browser Agent** — Type a task and G-Axis plans, navigates, clicks, fills forms, and completes multi-step workflows in your browser. It understands web pages through Gemini Vision, uses semantic UI graphs for Google Workspace apps, and always asks for confirmation before irreversible actions.

## Problem
People juggle 5+ tabs and 3+ tools to complete a single task. AI chatbots can answer questions but can't actually do anything in your browser. And existing AI browsers require downloading a separate application, losing all your logins, extensions, and browsing habits.

## Solution
G-Axis lives inside your existing browser as a sidepanel. No new app. No new logins. Your browser, your setup, your habits — G-Axis just adds the intelligence. Talk to it like a friend, delegate tasks to it like an assistant, and track your communication growth like a coach.

## How we built it

### Gemini APIs Used
- **Gemini Live API** (gemini-2.5-flash-native-audio) — Real-time bidirectional voice with WebSocket, native audio processing, input/output transcription
- **Gemini 2.5 Flash** — Task planning, function calling, session analysis, intent classification
- **Google Search** (Grounding) — Real-time web data in voice conversations
- **text-embedding-004** — Embedding-based memory retrieval for learned patterns

### Architecture
- **Chrome Extension** (Manifest V3) — Side Panel UI, Service Worker (message hub), Content Script (DOM intelligence + action execution), AudioWorklet (mic capture)
- **Python Backend** (FastAPI) — Multi-agent system with 7 specialist agents, 34 connector skills across 9 Google Workspace services
- **Google Cloud** — Cloud Run (hosting), Secret Manager (API keys), Cloud Build (Docker), Terraform (IaC)

### Key Technical Decisions
- **Direct WebSocket to Gemini Live** from extension service worker — zero-hop, zero-latency voice (no backend proxy)
- **OAuth2 short-lived tokens** — API key stays in Secret Manager, extension gets 60-min tokens at runtime
- **Gapless audio playback** — Scheduled AudioBufferSource start times instead of onended callbacks
- **AudioWorklet** with 4096-sample buffering for reliable mic capture
- **Semantic UI Graphs** — Pre-built node/edge models for Calendar, Gmail, Docs enabling deterministic form filling
- **Auto-reconnect** — Voice sessions survive Gemini's ~10min timeout with transparent reconnection (up to 20x)

## Challenges
- Chrome extension sidepanels can't access `getUserMedia` — solved with popup window + AudioWorklet + Port streaming
- Gemini Live native audio model doesn't support custom function calling (1008 errors) — separated voice (client-side, chat-only) from browser automation (server-side, full tools)
- Session timeouts with continuous audio streaming — removed client-side VAD, let Gemini handle silence detection natively
- Balancing conversation naturalness with response speed — 8 persona system prompts tuned for different voice styles

## What's next
- Firebase integration for cross-device conversation persistence
- Weekly progress reports with AI-generated coaching insights
- Group conversation scenarios (team meetings, panel interviews)
- Speech rate/pitch customization
- Mobile companion app

## Built with
Gemini Live API, Gemini 2.5 Flash, Google Search, Chrome Extension (MV3), Python, FastAPI, Google Cloud Run, Terraform, AudioWorklet, WebSocket

## Links
- **Live Backend**: https://gaxis-132388856648.us-central1.run.app
- **Health Check**: https://gaxis-132388856648.us-central1.run.app/health
- **Agent Card**: https://gaxis-132388856648.us-central1.run.app/.well-known/agent.json
