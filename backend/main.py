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
from fastapi.responses import JSONResponse

from backend.agent.core import GAxisAgent, TaskEvent

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("gaxis.server")

agent: GAxisAgent | None = None
connected_clients: set[WebSocket] = set()


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
    """Send event to all connected WebSocket clients."""
    data = json.dumps({"type": event.type, "task_id": event.task_id, "data": event.data})
    disconnected = set()
    for ws in connected_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.add(ws)
    connected_clients -= disconnected


# ─── WEBSOCKET ENDPOINT ──────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    logger.info(f"Client connected ({len(connected_clients)} total)")

    agent.on_event(broadcast_event)

    try:
        while True:
            message = await ws.receive_text()
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "run_task":
                instruction = data.get("instruction", "")
                mode = data.get("mode", "api")  # "api" or "extension"
                if instruction:
                    asyncio.create_task(_run_task(instruction, mode))
                else:
                    await ws.send_text(json.dumps({
                        "type": "error", "data": {"message": "No instruction provided"}
                    }))

            elif msg_type == "approve":
                if agent:
                    agent.respond_approval(True)

            elif msg_type == "deny":
                if agent:
                    agent.respond_approval(False)

            elif msg_type == "screenshot":
                # Extension sending a screenshot
                if agent:
                    agent.receive_screenshot(
                        screenshot_b64=data.get("screenshot", ""),
                        url=data.get("url", ""),
                        title=data.get("title", ""),
                    )

            elif msg_type == "dom_snapshot":
                # Extension sending a DOM snapshot
                if agent:
                    agent.receive_dom_snapshot(data.get("elements", []))

            elif msg_type == "dom_changed":
                # Extension reporting DOM mutations — log for context
                logger.debug(f"DOM changed: {len(data.get('changes', []))} mutations")

            elif msg_type == "action_result":
                # Extension reporting action execution result
                pass  # Future: handle action confirmation from extension

            elif msg_type == "stop":
                pass  # TODO: task cancellation

            else:
                await ws.send_text(json.dumps({
                    "type": "error",
                    "data": {"message": f"Unknown message type: {msg_type}"}
                }))

    except WebSocketDisconnect:
        connected_clients.discard(ws)
        logger.info(f"Client disconnected ({len(connected_clients)} total)")


async def _run_task(instruction: str, mode: str = "api") -> None:
    if not agent:
        return
    try:
        result = await agent.run_task(instruction, mode=mode)
        logger.info(f"Task {result.task_id} completed: {result.status}")
    except Exception as e:
        logger.error(f"Task execution error: {e}")
        await broadcast_event(TaskEvent("error", "unknown", {"message": str(e)}))


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
