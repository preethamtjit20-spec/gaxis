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

**Architecture**: The system has three layers — a Chrome extension (Manifest V3) as the client, a Python/FastAPI backend on Cloud Run, and Gemini APIs as the intelligence layer.

**Voice Pipeline**: The biggest technical challenge. Chrome extension sidepanels can't access `getUserMedia`, so I built a minimal popup window with an AudioWorklet processor that captures PCM 16kHz audio, streams it via Chrome ports to the service worker, which connects directly to Gemini's Live API over WebSocket. Audio responses come back at 24kHz and play through a gapless scheduler — each buffer is timed to start exactly when the previous one ends, eliminating the stuttering that `onended` callbacks cause.

**Persona System**: Each of the 8 personas is defined in `gemini-live.js` with a unique system prompt, voice name, and conversational style. The service worker creates a new `GeminiLiveClient` instance with the selected persona's config. Switching mid-conversation saves the current session for analysis, clears the transcript, and reconnects with the new persona.

**Browser Automation**: The backend runs a multi-agent system — an Orchestrator delegates to a FastLoop (one Gemini call per action step), a Planner (conversational task planning), and a Researcher (multi-source web scanning). 12 browser tools (click, type, navigate, scroll, fill_form, etc.) execute via the content script. A Policy Engine scores risk and gates sensitive actions.

**Analytics**: After each voice session, the transcript is sent to Gemini 2.5 Flash for analysis — intent classification, skill scoring, topic extraction, and summary generation. Results are stored locally with XP calculations, streak tracking, and a level system.

**Security**: The Gemini API key lives in Google Cloud Secret Manager. The backend generates short-lived OAuth2 access tokens (~60 minutes) via `/api/v`. The extension fetches a fresh token on each voice session — the key never touches client code, git, or network endpoints.

**Deployment**: Fully automated with a `deploy.sh` script and Terraform IaC (`terraform/main.tf`). Cloud Build creates Docker images, Cloud Run hosts the backend, and Cloud Scheduler triggers daily/weekly analytics jobs.

## Challenges I ran into

**Mic permissions in Chrome extensions** — Sidepanels and offscreen documents couldn't reliably get `getUserMedia` permission. I went through 4 approaches (direct sidepanel, offscreen document, full tab, popup window) before landing on a minimal popup that auto-requests permission and streams via AudioWorklet through a Chrome port.

**Gemini Live session stability** — Sessions would die after 6-10 seconds of silence because my initial VAD (Voice Activity Detection) was filtering out silence, making Gemini think the user disconnected. The fix: send continuous audio and let Gemini handle its own silence detection. Sessions would also crash with 1008 errors when browser tool calls were attempted — the native audio model doesn't support custom function calling. I separated voice (client-side, chat + Google Search only) from browser automation (server-side, full tool access).

**Audio playback quality** — The first implementation used `onended` callbacks to chain audio buffers, causing 5-20ms gaps between every chunk — speech sounded choppy and words were skipped. Switching to scheduled `source.start(preciseTime)` with gapless timing fixed this completely.

**Conversation context across reconnects** — Gemini Live sessions timeout after ~10 minutes. I built transparent auto-reconnection (up to 20 times) so the voice session survives for over an hour of continuous conversation. The user sees a brief "Extending session..." status and the conversation continues.

**API key security** — The key was accidentally committed to the public repo. I used `git filter-branch` to scrub it from the entire git history, rotated the key, and moved to an OAuth2 token-based flow where the key never leaves Cloud Run.

## Accomplishments that I'm proud of

**Zero-latency voice** — The direct WebSocket connection from the Chrome extension to Gemini Live (no backend proxy) delivers genuinely real-time conversation. Users can interrupt mid-sentence and the agent stops immediately.

**8 personas with live switching** — Switching from "Friendly Buddy" to "Job Interviewer" mid-conversation — hearing a completely different voice and personality respond — feels like magic. The previous session is saved and analyzed automatically.

**The analytics dashboard** — Seeing your communication skills scored after every conversation, watching your XP grow and streak build — it turns voice chat from a novelty into a tool for genuine self-improvement.

**End-to-end cloud deployment** — One command (`./deploy.sh gaxis-488323`) sets up APIs, secrets, builds the Docker image, and deploys to Cloud Run. Terraform manages the entire infrastructure. The API key never touches client code.

**Production-grade security** — OAuth2 short-lived tokens, Secret Manager, CORS restrictions, path traversal protection, no hardcoded credentials anywhere in the codebase or git history.

## What I learned

**Gemini Live API is powerful but opinionated** — It handles voice activity detection, turn-taking, and interruption natively. Fighting it (like adding client-side VAD) causes problems. Working with its design (continuous audio stream, let it manage silence) produces natural conversations.

**Chrome extension APIs have surprising gaps** — MV3 service workers can't show permission dialogs, sidepanels can't access getUserMedia, offscreen documents have limited capabilities. Building a voice-enabled extension requires creative workarounds.

**Audio engineering matters** — The difference between choppy speech (onended callbacks) and smooth speech (scheduled playback) is subtle in code but massive in user experience. Gapless audio scheduling was the single change that made the voice feature feel production-ready.

**Personas transform the experience** — A generic chatbot feels like a tool. A "Friendly Buddy" with a casual voice feels like a friend. A "Job Interviewer" with a professional tone feels like genuine practice. The persona system is simple technically but transformative for user engagement.

**Security is a journey** — I went from hardcoded API key → environment variable → settings input → network fetch → OAuth2 tokens. Each step was driven by a real vulnerability I discovered or someone pointed out.

## What's next for G-Axis

**Firebase integration** — Moving conversation storage from local JSON files to Cloud Firestore for cross-device persistence and multi-user support.

**Weekly progress reports** — Automated AI-generated coaching reports every Sunday analyzing the week's conversations, identifying improvement areas, and setting goals.

**Group conversation scenarios** — Multi-persona sessions for practicing team meetings, panel interviews, or group discussions with multiple AI voices.

**Voice-triggered browser actions** — Bringing browser automation back into voice sessions with a safe, intent-confirmed approach: "Open my Calendar" → agent confirms → executes.

**Mobile companion** — A lightweight mobile app that connects to the same backend for voice practice on the go.

**Community personas** — Let users create and share custom personas with their own system prompts and voice configurations.
