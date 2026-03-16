"""G-Axis Backend Server.

FastAPI server with WebSocket for real-time agent communication.
Supports both API mode (Playwright) and Extension mode (Chrome extension).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from backend.agent.core import GAxisAgent, TaskEvent
from backend.agent.live_session import LiveSession

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("gaxis.server")

agent: GAxisAgent | None = None
task_running: bool = False
task_paused: bool = False
task_cancel_event: asyncio.Event | None = None
task_pause_event: asyncio.Event | None = None  # Cleared = paused, Set = running
current_task: asyncio.Task | None = None
paused_instruction: str = ""  # Remember what we were doing

# Lock to prevent concurrent task execution from racing on globals
_task_lock = asyncio.Lock()
_live_lock = asyncio.Lock()
_live_starting = False

# Gemini Live Audio session (one per server — single-user for now)
live_session: LiveSession | None = None

# Each connected client gets a queue for outgoing messages
client_queues: dict[WebSocket, asyncio.Queue] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    agent = GAxisAgent(
        api_key=os.environ.get("GOOGLE_API_KEY"),
        firestore_project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
        headless=os.environ.get("HEADLESS", "true").lower() == "true",
    )
    await agent.start()
    logger.info("G-Axis server started")
    yield
    await agent.stop()
    logger.info("G-Axis server stopped")


app = FastAPI(title="G-Axis", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── EVENT BROADCASTING ──────────────────────────────────────

async def broadcast_event(event: TaskEvent) -> None:
    """Queue event for all connected WebSocket clients."""
    data = json.dumps({"type": event.type, "task_id": event.task_id, "data": event.data})
    logger.info(f"Broadcasting: {event.type} (task={event.task_id})")
    dead = []
    for ws, queue in client_queues.items():
        try:
            queue.put_nowait(data)
        except Exception as e:
            logger.warning(f"Broadcast queue error for client: {e}")
            dead.append(ws)
    for ws in dead:
        client_queues.pop(ws, None)


# ─── WEBSOCKET ENDPOINT ──────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global live_session, _live_starting
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue()
    client_queues[ws] = queue
    logger.info(f"Client connected ({len(client_queues)} total)")

    agent.on_event(broadcast_event)

    async def send_loop():
        """Drains the queue and sends messages to the client."""
        try:
            while True:
                data = await queue.get()
                await ws.send_text(data)
        except Exception as e:
            logger.debug(f"Send loop ended: {e}")  # WebSocket closed

    sender = asyncio.create_task(send_loop())
    current_task = None

    try:
        while True:
            message = await ws.receive_text()
            data = json.loads(message)
            msg_type = data.get("type", "")

            # Log non-audio/non-spam message types
            if msg_type not in ("live_audio_in", "ping", "dom_changed"):
                logger.info(f"WS message: {msg_type}")

            if msg_type == "plan_chat":
                # Conversation planner — chat before execution
                user_message = data.get("message", "")
                if agent and user_message:
                    try:
                        result = await agent.plan_chat(user_message)
                        queue.put_nowait(json.dumps({
                            "type": "plan_response",
                            "data": result,
                        }))
                    except Exception as e:
                        logger.error(f"Plan chat error: {e}")
                        queue.put_nowait(json.dumps({
                            "type": "plan_response",
                            "data": {
                                "message": "Let me just help you with that directly.",
                                "ready_to_execute": True,
                                "plan": {"refined_instruction": user_message},
                                "refined_instruction": user_message,
                            },
                        }))

            elif msg_type == "run_task":
                instruction = data.get("instruction", "")
                mode = data.get("mode", "api")
                if instruction:
                    current_task = asyncio.create_task(_run_task(instruction, mode))
                else:
                    queue.put_nowait(json.dumps({
                        "type": "error", "data": {"message": "No instruction provided"}
                    }))

            elif msg_type == "approve":
                if agent:
                    edits = data.get("edits")
                    if edits:
                        logger.info(f"User edits on confirmation card: {edits}")
                        agent.receive_user_edits(edits)
                    agent.respond_approval(True)

            elif msg_type == "deny":
                if agent:
                    agent.respond_approval(False)

            elif msg_type == "screenshot":
                logger.info(f"Received screenshot from extension (url={data.get('url', '')[:60]})")
                if agent:
                    agent.receive_screenshot(
                        screenshot_b64=data.get("screenshot", ""),
                        url=data.get("url", ""),
                        title=data.get("title", ""),
                    )

            elif msg_type == "dom_snapshot":
                if agent:
                    agent.receive_dom_snapshot(data.get("elements", []))

            elif msg_type == "dom_changed":
                logger.debug(f"DOM changed: {len(data.get('changes', []))} mutations")

            elif msg_type == "dom_blocker":
                if agent:
                    status = data.get("status", "blocked")
                    element = data.get("element", "?")
                    text = data.get("text", "")[:100]
                    logger.info(f"DOM blocker: status={status} el={element} text={text[:60]}")
                    if status == "blocked":
                        # Unknown blocker — queue for Gemini vision recovery
                        agent.receive_blocker(data)
                    else:
                        logger.info(f"Blocker auto-dismissed: {element}")

            elif msg_type == "action_result":
                # Extension sends back the actual result of executing an action
                if agent:
                    agent.tool_executor.receive_action_result(data.get("result", {}))
                    logger.info(f"Action result received: success={data.get('result', {}).get('success')}")


            elif msg_type == "ping":
                queue.put_nowait(json.dumps({"type": "pong"}))

            elif msg_type == "user_input":
                if agent:
                    text = data.get("text", "")
                    # Mid-task steering: user typed guidance while agent is executing
                    if data.get("steering") and text:
                        agent.receive_steering(text)
                        logger.info(f"Mid-task steering: {text[:80]}")
                    else:
                        agent.respond_user_input(text)

            elif msg_type == "set_preferences":
                if agent:
                    agent.set_user_preferences(data.get("preferences", {}))

            elif msg_type == "get_connectors":
                if agent:
                    skills_info = []
                    for skill in agent.connectors.all_skills():
                        skills_info.append({
                            "name": skill.full_name,
                            "description": skill.description,
                            "connector": skill.connector,
                            "tags": skill.tags,
                            "mode": skill.mode.value,
                        })
                    queue.put_nowait(json.dumps({
                        "type": "connectors_info",
                        "data": {"skills": skills_info},
                    }))

            elif msg_type == "stop":
                logger.info("Stop requested by user")
                if task_cancel_event:
                    task_cancel_event.set()
                if current_task and not current_task.done():
                    current_task.cancel()
                async with _task_lock:
                    task_running = False
                    task_paused = False
                await broadcast_event(TaskEvent("task_stopped", "unknown", {
                    "message": "Got it — I've stopped. Let me know if you'd like me to pick this up again."
                }))

            elif msg_type == "pause":
                # Graceful pause — agent finishes current action then waits
                logger.info("Pause requested by user")
                task_paused = True
                if agent and hasattr(agent, 'pause_event'):
                    agent.pause_event = True
                await broadcast_event(TaskEvent("task_paused", "unknown", {
                    "message": "Sure, I'll pause here. Take your time — I'll keep track of where we are."
                }))

            elif msg_type == "resume":
                # Resume from pause
                logger.info("Resume requested by user")
                task_paused = False
                if agent and hasattr(agent, 'pause_event'):
                    agent.pause_event = False
                await broadcast_event(TaskEvent("task_resumed", "unknown", {
                    "message": "Thanks — I'll pick up right where we left off."
                }))

            elif msg_type == "takeover":
                # Human wants manual control — agent steps aside gracefully
                logger.info("Human takeover requested")
                task_paused = True
                if agent and hasattr(agent, 'pause_event'):
                    agent.pause_event = True
                await broadcast_event(TaskEvent("human_takeover", "unknown", {
                    "message": "You've got it! I'll stay right here in case you need me. Just say 'continue' when you want me to take over again."
                }))

            elif msg_type == "give_back":
                # User gives control back to agent
                logger.info("User giving control back to agent")
                task_paused = False
                if agent and hasattr(agent, 'pause_event'):
                    agent.pause_event = False
                await broadcast_event(TaskEvent("agent_resumed", "unknown", {
                    "message": "Thanks! I'll take it from here and continue where we left off."
                }))

            # ─── GEMINI LIVE AUDIO ──────────────────────────────

            elif msg_type == "live_start":
                async with _live_lock:
                    if _live_starting:
                        logger.warning("Live start already in progress, ignoring")
                        continue
                    logger.info("Starting Gemini Live Audio session")
                    if live_session and live_session.is_active:
                        await live_session.stop()
                        live_session = None

                    async def _live_audio_out(b64):
                        queue.put_nowait(json.dumps({"type": "live_audio_out", "data": b64}))

                    async def _live_transcript(direction, text):
                        queue.put_nowait(json.dumps({"type": f"live_transcript_{direction}", "data": {"text": text}}))

                    async def _live_status(status, d):
                        queue.put_nowait(json.dumps({"type": "live_status", "data": {"status": status, **d}}))

                    live_session = LiveSession(
                        genai_client=agent.genai_client,
                        tool_executor=agent.tool_executor,
                        emit_fn=agent._emit,
                        audio_out_fn=_live_audio_out,
                        transcript_fn=_live_transcript,
                        status_fn=_live_status,
                        get_screenshot_fn=agent._get_screenshot_from_extension,
                        policy_engine=agent.policy,
                        ui_graph_registry=agent.ui_graph_registry,
                    )
                    live_session._connector_registry = agent.connectors

                    _live_starting = True
                    try:
                        await live_session.start()
                        if agent._ext_screenshot:
                            await live_session.send_screenshot(agent._ext_screenshot)
                        if agent._ext_url:
                            live_session._current_url = agent._ext_url
                    except Exception as e:
                        logger.error(f"Failed to start Live session: {e}")
                        queue.put_nowait(json.dumps({
                            "type": "live_status",
                            "data": {"status": "error", "message": str(e)},
                        }))
                        live_session = None
                    finally:
                        _live_starting = False

            elif msg_type == "live_audio_in":
                if live_session and live_session.is_active:
                    await live_session.send_audio(data.get("data", ""))

            elif msg_type == "live_text":
                if live_session and live_session.is_active:
                    await live_session.send_text(data.get("text", ""))

            elif msg_type == "live_stop":
                async with _live_lock:
                    logger.info("Stopping Gemini Live Audio session")
                    if live_session:
                        await live_session.stop()
                        live_session = None

            else:
                queue.put_nowait(json.dumps({
                    "type": "error",
                    "data": {"message": f"Unknown message type: {msg_type}"}
                }))

    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        client_queues.pop(ws, None)
        # Clean up live session if this client owned it
        if live_session:
            await live_session.stop()
            live_session = None
        logger.info(f"Client disconnected ({len(client_queues)} total)")


async def _run_task(instruction: str, mode: str = "api") -> None:
    global task_running, task_cancel_event, current_task
    if not agent:
        return

    # Acquire lock to prevent two concurrent run_task calls from racing
    async with _task_lock:
        if task_running:
            await broadcast_event(TaskEvent("error", "unknown", {"message": "Another task is already running. Please wait."}))
            return
        task_running = True
        task_cancel_event = asyncio.Event()
        # Pass cancel event to agent so graph loop can check it
        agent.cancel_event = task_cancel_event

    try:
        result = await agent.run_task(instruction, mode=mode)
        logger.info(f"Task {result.task_id} completed: {result.status}")
    except asyncio.CancelledError:
        logger.info("Task cancelled by user")
        await broadcast_event(TaskEvent("task_failed", "unknown", {"error": "Task stopped by user"}))
    except Exception as e:
        logger.error(f"Task execution error: {e}")
        await broadcast_event(TaskEvent("error", "unknown", {"message": str(e)}))
    finally:
        async with _task_lock:
            task_running = False
            task_cancel_event = None


# ─── REST ENDPOINTS ──────────────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "agent": agent is not None})


@app.get("/.well-known/agent.json")
async def agent_card():
    """Agent Card for A2A discovery."""
    return JSONResponse({
        "name": "G-Axis",
        "description": "Multi-agent AI browser system with supervised autonomy. Uses Gemini Vision for UI understanding, multi-agent orchestration for task execution, and retrieval-based memory for learning.",
        "version": "0.2.0",
        "provider": {"name": "G-Axis", "url": "https://github.com/preethams/gaxis"},
        "capabilities": [
            "web_navigation", "visual_ui_understanding",
            "form_filling", "data_extraction", "supervised_execution",
            "multi_agent_orchestration", "retrieval_memory",
            "dom_intelligence", "anti_bot_resilience",
            "google_workspace_integration", "connector_skills",
        ],
        "architecture": {
            "type": "multi_agent_graph",
            "agents": [
                {"name": "perceiver", "role": "Screenshot + DOM analysis via Gemini Vision"},
                {"name": "orchestrator", "role": "Task decomposition and agent delegation"},
                {"name": "navigator", "role": "Page navigation with Gemini tool calling"},
                {"name": "form_filler", "role": "Form interaction with Gemini tool calling"},
                {"name": "data_extractor", "role": "Structured data extraction"},
                {"name": "verifier", "role": "Task completion validation"},
            ],
            "perception": "Hybrid — Gemini Vision (screenshots) + DOM snapshots (precise coordinates)",
            "execution": "Gemini native function calling → browser tool dispatch",
        },
        "endpoints": {
            "task": {"method": "POST", "path": "/api/task"},
            "websocket": {"path": "/ws"},
            "health": {"method": "GET", "path": "/health"},
            "agent_card": {"method": "GET", "path": "/.well-known/agent.json"},
            "memory": {"method": "GET", "path": "/api/memory/{domain}"},
            "patterns": {"method": "GET", "path": "/api/patterns"},
        },
        "tools": [
            {"name": "click", "description": "Click at screen coordinates"},
            {"name": "type_text", "description": "Type text into an input field"},
            {"name": "navigate", "description": "Navigate to a URL"},
            {"name": "scroll", "description": "Scroll page up or down"},
            {"name": "press_key", "description": "Press a keyboard key"},
            {"name": "hover", "description": "Hover over an element"},
            {"name": "extract_data", "description": "Extract structured data from page"},
            {"name": "wait", "description": "Wait for page to load"},
        ],
        "auth": {"type": "none"},
        "memory": {
            "working": "Per-task state (dies with task)",
            "episodic": "Per-domain task history with outcomes",
            "semantic": "Cross-site learned patterns (5 built-in)",
            "retrieval": "Embedding-based similarity search across all experiences (Gemini text-embedding-004)",
        },
    })


@app.post("/api/task")
async def create_task(body: dict):
    """REST endpoint for task execution (A2A compatible)."""
    instruction = body.get("instruction", "")
    if not instruction:
        return JSONResponse({"error": "No instruction provided"}, status_code=400)
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)

    mode = body.get("mode", "api")
    asyncio.create_task(_run_task(instruction, mode))
    return JSONResponse({"status": "started", "instruction": instruction, "mode": mode})


@app.get("/api/memory/{domain}")
async def get_memory(domain: str):
    """Get episodic memory for a domain."""
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    episodes = await agent.memory.recall_episodes(domain)
    return JSONResponse({
        "domain": domain,
        "episodes": [
            {
                "instruction": ep.instruction,
                "success": ep.success,
                "steps_taken": ep.steps_taken,
                "duration_ms": ep.duration_ms,
                "obstacles": ep.obstacles,
                "timestamp": ep.timestamp,
            }
            for ep in episodes
        ],
    })


@app.get("/api/connectors")
async def get_connectors():
    """List all registered connectors and their skills."""
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    connectors = []
    for conn in agent.connectors.connectors.values():
        skills = []
        for skill in conn.skills.values():
            skills.append({
                "name": skill.name,
                "full_name": skill.full_name,
                "description": skill.description,
                "mode": skill.mode.value,
                "start_url": skill.start_url,
                "tags": skill.tags,
                "params": [
                    {"name": p.name, "description": p.description, "type": p.type, "required": p.required}
                    for p in skill.params
                ],
            })
        connectors.append({
            "name": conn.name,
            "description": conn.description,
            "icon": conn.icon,
            "category": conn.category,
            "skills": skills,
        })
    return JSONResponse({"connectors": connectors})


@app.get("/api/skills/search")
async def search_skills(q: str = ""):
    """Search for skills matching a query."""
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    skills = agent.connectors.find_skills(q) if q else agent.connectors.all_skills()
    return JSONResponse({
        "query": q,
        "skills": [
            {
                "name": s.full_name,
                "description": s.description,
                "mode": s.mode.value,
                "tags": s.tags,
                "examples": s.examples,
            }
            for s in skills[:20]
        ],
    })


@app.get("/api/patterns")
async def get_patterns():
    """Get all known semantic patterns."""
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    patterns = await agent.memory.get_patterns()
    return JSONResponse({
        "patterns": [
            {
                "id": p.pattern_id,
                "name": p.name,
                "description": p.description,
                "confidence": p.confidence,
                "seen_count": p.seen_count,
            }
            for p in patterns
        ],
    })


# ─── EXECUTION REPLAY API ────────────────────────────────

@app.get("/api/replay/{task_id}")
async def get_replay(task_id: str):
    """Get execution replay for a task — timeline of actions for UI playback."""
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    summary = agent.replay.get_session_summary(task_id)
    if not summary:
        return JSONResponse({"error": "Replay not found"}, status_code=404)
    return JSONResponse(summary)


@app.get("/api/replays")
async def list_replays():
    """List all saved execution replays."""
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    replays = agent.replay.list_replays()
    return JSONResponse({"replays": replays})


@app.get("/api/doc/{filename}")
async def download_doc(filename: str):
    """Download a generated .docx research document."""
    filepath = os.path.join("research-docs", filename)
    if not os.path.exists(filepath):
        return JSONResponse({"error": "Document not found"}, status_code=404)
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )


class TranscriptClassifyRequest(BaseModel):
    transcript: str


@app.post("/api/classify-transcript")
async def classify_transcript(req: TranscriptClassifyRequest):
    """Classify a voice transcript: intent, summary, action items, key decisions, topics."""
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)
    try:
        from google.genai import types
        response = await agent.genai_client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                "Analyze this voice conversation transcript and return a JSON object with:\n"
                "- intent: one of 'task' (user asked agent to do something), 'research' (information gathering), "
                "'planning' (scheduling/organizing), 'important' (key decisions or sensitive info), "
                "'casual' (small talk, greetings only), 'unintentional' (accidental recording, test mic)\n"
                "- summary: 2-3 sentence summary of the conversation\n"
                "- action_items: list of follow-up actions mentioned (empty array if none)\n"
                "- key_decisions: list of decisions made (empty array if none)\n"
                "- topics: list of main topics discussed\n\n"
                f"Transcript:\n{req.transcript}\n\nJSON:"
            ),
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=512,
                response_mime_type="application/json",
            ),
        )
        import json as json_mod
        result = json_mod.loads(response.text)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Transcript classification failed: {e}")
        return JSONResponse({"intent": "important", "summary": "Classification failed", "action_items": [], "key_decisions": [], "topics": []})


class TranscriptRequest(BaseModel):
    title: str
    content: str


@app.post("/api/save-transcript")
async def save_transcript(req: TranscriptRequest):
    """Save a voice conversation transcript as .docx."""
    from backend.tools.doc_converter import markdown_to_docx
    try:
        filepath = markdown_to_docx(req.content, req.title)
        filename = os.path.basename(filepath)
        download_url = f"http://localhost:{os.environ.get('PORT', '8000')}/api/doc/{filename}"
        return JSONResponse({"success": True, "download_url": download_url, "filename": filename})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# ─── CONVERSATION ANALYTICS ──────────────────────────────


class AnalyzeSessionRequest(BaseModel):
    session_id: str = ""
    persona: str = "friend"
    started_at: str = ""
    ended_at: str = ""
    duration_secs: int = 0
    transcript: str = ""


@app.post("/api/analyze-session")
async def analyze_session(req: AnalyzeSessionRequest):
    """Analyze a completed voice session — skills, insights, XP."""
    if not agent:
        return JSONResponse({"error": "Agent not initialized"}, status_code=503)

    from backend.analytics.store import save_session, SessionRecord

    # Count messages
    lines = [l.strip() for l in req.transcript.split("\n") if l.strip()]
    user_lines = [l for l in lines if l.startswith("**You**")]
    agent_lines = [l for l in lines if l.startswith("**G-Axis**")]
    user_words = sum(len(l.split()) for l in user_lines)
    agent_words = sum(len(l.split()) for l in agent_lines)

    # Skip trivial sessions
    if len(user_lines) < 2:
        return JSONResponse({"skipped": True, "reason": "Too short"})

    # Analyze with Gemini
    skills = {"confidence": 50, "clarity": 50, "engagement": 50, "listening": 50, "pacing": 50}
    topics = []
    summary = ""
    intent = "casual"
    action_items = []

    try:
        from google.genai import types
        import re as _re

        # Truncate transcript to avoid token limits
        transcript_text = req.transcript[:3000]

        response = await agent.genai_client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                'You are a conversation analyst. Analyze this voice conversation transcript.\n\n'
                f'Transcript:\n"""\n{transcript_text}\n"""\n\n'
                'Return a JSON object with exactly these fields:\n'
                '{"intent":"casual","summary":"Brief summary here","topics":["topic1"],'
                '"action_items":[],"skills":{"confidence":65,"clarity":70,"engagement":60,"listening":55,"pacing":50},'
                '"recommendation":"One tip here"}\n\n'
                'Rules:\n'
                '- intent: one of task, research, planning, important, casual\n'
                '- skills: scores 0-100 based on how the USER communicated\n'
                '- summary: 1-2 sentences\n'
                '- Return ONLY valid JSON, no markdown, no explanation'
            ),
            config=types.GenerateContentConfig(
                temperature=0.0, max_output_tokens=1024,
                response_mime_type="application/json",
            ),
        )

        # Robust JSON extraction
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = _re.sub(r'^```\w*\n?', '', raw)
            raw = _re.sub(r'\n?```$', '', raw)
            raw = raw.strip()
        result = json.loads(raw)

        skills = result.get("skills", skills)
        topics = result.get("topics", [])
        summary = result.get("summary", "")
        intent = result.get("intent", "casual")
        action_items = result.get("action_items", [])
        recommendation = result.get("recommendation", "")
        logger.info(f"Session analyzed: intent={intent}, skills={skills}")
    except Exception as e:
        logger.error(f"Session analysis failed: {e}")
        recommendation = ""

    # Save to analytics store
    record = SessionRecord(
        session_id=req.session_id or f"session_{int(time.time())}",
        persona=req.persona,
        started_at=req.started_at or datetime.now().isoformat(),
        ended_at=req.ended_at or datetime.now().isoformat(),
        duration_secs=req.duration_secs,
        message_count=len(user_lines) + len(agent_lines),
        user_word_count=user_words,
        agent_word_count=agent_words,
        topics=topics,
        intent=intent,
        summary=summary,
        skills=skills,
        action_items=action_items,
    )

    from datetime import datetime as dt
    xp_result = save_session(record)

    return JSONResponse({
        "session_id": record.session_id,
        "summary": summary,
        "intent": intent,
        "topics": topics,
        "skills": skills,
        "action_items": action_items,
        "recommendation": recommendation,
        "xp_earned": xp_result["xp_earned"],
        "level": xp_result["level"],
        "streak": xp_result["streak"],
    })


@app.get("/api/dashboard")
async def get_dashboard():
    """Get dashboard stats for the sidepanel."""
    from backend.analytics.store import get_stats, get_insights, get_recent_sessions
    stats = get_stats()
    insights = get_insights()
    recent = get_recent_sessions(5)
    return JSONResponse({
        "stats": stats,
        "insights": insights,
        "recent_sessions": recent,
    })


import time as _time
from datetime import datetime
