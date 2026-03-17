# G-Axis

## Inspiration

I was tired of the tab-switching dance. ChatGPT in one tab, Google Calendar in another, research in a third — six tabs open just to plan a single meeting. Every AI tool lives in its own silo, disconnected from where the actual work happens: the browser.

Then I thought — what if the browser itself was intelligent? Not a new browser, not another chatbot, but something that lives inside Chrome, sees what I see, talks like a friend, and actually does things for me. That's how G-Axis was born.

The Gemini Live Agent Challenge was the perfect catalyst. Gemini's Live API offered something no other model had — real-time, bidirectional native audio. Not text-to-speech. Actual voice conversation. I wanted to build something that felt like having a smart friend sitting next to you while you browse.

## What it does

G-Axis is a Chrome extension with two core capabilities:

**Voice AI Companion** — Click the mic and start talking. G-Axis connects directly to Gemini's Live API for real-time voice conversations. It has 8 AI personas — Friendly Buddy, Wise Mentor, Creative Partner, Chill Companion, Professional Coach, Job Interviewer, Friendly Debater, and Storyteller. Each has its own voice (Puck, Charon, Aoede, Kore, Fenrir) and personality. Switch personas mid-conversation seamlessly.

It uses Google Search for grounding — ask "What's happening with AI this week?" and it searches the web live, answering with current data, not stale training knowledge.

Every conversation is analyzed by Gemini for 5 communication skills — Confidence, Clarity, Engagement, Listening, and Pacing. Users earn XP, level up, and track daily streaks on an analytics dashboard.

**Autonomous Browser Agent** — Type a task like "Plan a 5-day Japan itinerary" and G-Axis takes over. It opens a workspace tab, researches across multiple websites, synthesizes the information, and generates a downloadable .docx document. Type "Schedule a meeting tomorrow at 10am" and it opens Google Calendar, fills in the event details, and saves it.

It uses Gemini Vision to understand screenshots, semantic UI graphs for Google Workspace apps, and a policy engine that requires approval before any risky action. You stay in control.

## How I built it

**Built solo.**

### Gemini APIs Used
- **Gemini Live API** (`gemini-2.5-flash-native-audio-preview`) — real-time bidirectional voice
- **Gemini 2.5 Flash** — task planning, function calling, session analysis, intent classification
- **Gemini Vision** — screenshot understanding for browser automation
- **Google Search** (Grounding) — real-time web data in voice conversations
- **text-embedding-004** — embedding-based memory retrieval

### Google Cloud Services
- **Cloud Run** — backend hosting (FastAPI, autoscaling)
- **Secret Manager** — API key storage + OAuth2 token generation
- **Cloud Build** — Docker image CI/CD
- **Cloud Scheduler** — daily/weekly analytics jobs
- **Terraform** — Infrastructure as Code

### Architecture

The system has three layers — a Chrome extension (Manifest V3) as the client, a Python/FastAPI backend on Cloud Run, and Gemini APIs as the intelligence layer.

**Voice Pipeline**: Chrome extension sidepanels can't access `getUserMedia`, so I built a minimal popup window with an AudioWorklet processor that captures PCM 16kHz audio, streams it via Chrome ports to the service worker, which connects directly to Gemini's Live API over WebSocket. Audio responses come back at 24kHz and play through a gapless scheduler — each buffer is timed to start exactly when the previous one ends, eliminating the stuttering that `onended` callbacks cause.

**Persona System**: Each of the 8 personas is defined in `gemini-live.js` with a unique system prompt, voice name, and conversational style. The service worker creates a new `GeminiLiveClient` instance with the selected persona's config. Switching mid-conversation saves the current session for analysis, clears the transcript, and reconnects with the new persona.

**Browser Automation**: The backend runs a multi-agent system — an Orchestrator delegates to a FastLoop (one Gemini call per action step), a Planner (conversational task planning), and a Researcher (multi-source web scanning). 12 browser tools (click, type, navigate, scroll, fill_form, etc.) execute via the content script. A Policy Engine scores risk and gates sensitive actions.

**Analytics**: After each voice session, the transcript is sent to Gemini 2.5 Flash for analysis — intent classification, skill scoring, topic extraction, and summary generation. Results are stored locally with XP calculations, streak tracking, and a level system.

**Security**: The Gemini API key lives in Google Cloud Secret Manager. The backend generates short-lived OAuth2 access tokens (~60 minutes) via `/api/v`. The extension fetches a fresh token on each voice session — the key never touches client code, git, or network endpoints.

**Deployment**: Fully automated with a `deploy.sh` script and Terraform IaC (`terraform/main.tf`). Cloud Build creates Docker images, Cloud Run hosts the backend, and Cloud Scheduler triggers daily/weekly analytics jobs.

## Challenges I ran into

### Blocker 1: Chrome Extension Mic Permission (6+ hours)
`getUserMedia` throws `NotAllowedError` in sidepanels and offscreen documents. Tried 4 approaches — direct sidepanel, offscreen document, full tab, popup window. **Solution**: Minimal popup window with AudioWorklet that auto-requests permission and streams PCM audio via Chrome ports to the service worker.

### Blocker 2: Gemini Live Session Dying After First Response (4+ hours)
After Gemini responded once, the session would close silently. **Root cause**: Our client-side VAD was filtering silence, making Gemini think the user disconnected. **Solution**: Removed client-side VAD entirely. Send continuous audio — Gemini handles its own silence detection natively.

### Blocker 3: 1008 "Operation Not Implemented" Crashes (3+ hours)
Browser tool calls (click, navigate) during voice crashed with `1008 policy violation`. **Root cause**: The native audio model doesn't support custom function declarations. **Solution**: Separated voice (client-side, `google_search` only) from browser automation (server-side, full tool access).

### Blocker 4: Audio Playback Stuttering (2+ hours)
Words skipping, choppy speech. **Root cause**: `onended` callbacks had 5-20ms gaps between chunks. **Solution**: Gapless scheduled playback — each `AudioBufferSource` starts at the exact nanosecond the previous one ends.

### Blocker 5: Session Timeout After ~10 Minutes
Gemini Live WebSocket closes after ~10 minutes. **Solution**: Transparent auto-reconnection up to 20 times. User sees brief "Extending session..." — conversations last 3+ hours.

### Blocker 6: API Key Exposed in Public Repo
Key was hardcoded and pushed to GitHub. **Solution**: `git filter-branch` to scrub history, rotated the key, moved to OAuth2 flow — key stays in Secret Manager, extension gets 60-min tokens at runtime.

### Blocker 7: localhost URLs in Production
After Cloud Run deployment, downloads pointed to `localhost:8000`. **Solution**: Changed all URLs to relative paths, resolved against `settings.backendUrl`.

### Blocker 8: Service Worker Registration Failed
`await` inside sync `onMessage` listener broke MV3 module loading. **Solution**: Wrapped handler in async IIFE with `return true` for async response channel.

### Blocker 9: CORS Blocking Extension Requests
`chrome-extension://*` isn't a valid CORS pattern. **Solution**: `allow_origins=["*"]` with `allow_credentials=False` — safe since auth uses OAuth tokens, not cookies.

### Blocker 10: Cloud Run File Persistence
Generated `.docx` files disappeared between requests. **Root cause**: Ephemeral containers. **Solution**: `min-instances=1` to keep container warm.

## Accomplishments that I'm proud of

**Zero-latency voice** — Direct WebSocket from Chrome extension to Gemini Live (no backend proxy). Users can interrupt mid-sentence and the agent stops immediately.

**8 personas with live switching** — Switching from "Friendly Buddy" to "Job Interviewer" mid-conversation — hearing a completely different voice and personality — feels like magic. Previous session auto-saves and gets analyzed.

**The analytics dashboard** — Communication skills scored after every conversation, XP growth, streak tracking — turns voice chat from a novelty into a self-improvement tool.

**End-to-end cloud deployment** — One command (`./deploy.sh gaxis-488323`) deploys everything. Terraform manages all infrastructure. API key never touches client code.

**Production-grade security** — OAuth2 short-lived tokens, Secret Manager, CORS restrictions, path traversal protection, git history scrubbed of all credentials.

## What I learned

**Gemini Live API is powerful but opinionated** — It handles VAD, turn-taking, and interruption natively. Fighting it (adding client-side VAD) causes problems. Working with its design (continuous audio, let it manage silence) produces natural conversations.

**Chrome extension APIs have surprising gaps** — MV3 service workers can't show permission dialogs, sidepanels can't access getUserMedia, offscreen documents have limited capabilities. Building voice-enabled extensions requires creative workarounds.

**Audio engineering matters** — The difference between choppy speech (onended callbacks) and smooth speech (scheduled playback) is subtle in code but massive in user experience.

**Personas transform the experience** — A generic chatbot feels like a tool. A "Friendly Buddy" with a casual voice feels like a friend. A "Job Interviewer" with a professional tone feels like genuine practice. Simple technically, transformative for engagement.

**Security is a journey** — Hardcoded key → env variable → settings input → network fetch → OAuth2 tokens. Each step was driven by a real vulnerability discovered in production.

## What's next for G-Axis

**Firebase integration** — Cloud Firestore for cross-device conversation persistence and multi-user support.

**Weekly progress reports** — AI-generated coaching reports every Sunday analyzing conversations, identifying improvement areas, and setting goals.

**Group conversation scenarios** — Multi-persona sessions for team meetings, panel interviews, or group discussions with multiple AI voices.

**Voice-triggered browser actions** — Bringing browser automation back into voice sessions with safe, intent-confirmed execution.

**Mobile companion** — Lightweight mobile app connected to the same backend for voice practice on the go.

**Community personas** — Users create and share custom personas with their own system prompts and voice configurations.

## Try it

- **Live backend**: https://gaxis-132388856648.us-central1.run.app/health
- **GitHub**: https://github.com/preethamtjit20-spec/gaxis
- **Agent Card**: https://gaxis-132388856648.us-central1.run.app/.well-known/agent.json

---

*Built for the [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/). Your browser already works — G-Axis makes it intelligent.*
