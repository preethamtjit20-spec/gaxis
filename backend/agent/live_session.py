"""Gemini Live Audio Session — real-time bidirectional voice with browser tool calling.

Connects to Gemini's Live API for streaming audio in/out while the agent
can still call browser tools (click, type, navigate, etc.) mid-conversation.
The user talks, Gemini responds with voice AND executes actions.

Audio format:
  Input:  PCM 16-bit, 16kHz, mono, little-endian
  Output: PCM 16-bit, 24kHz, mono, little-endian
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Callable, Awaitable

from google import genai
from google.genai import types

from backend.tools.definitions import ALL_TOOLS
from backend.tools.executor import ToolExecutor
from backend.policy.engine import PolicyEngine

logger = logging.getLogger("gaxis.live")

LIVE_MODEL = "gemini-live-2.5-flash-native-audio"

LIVE_SYSTEM = """You are G-Axis — a warm, capable AI browser assistant having a real-time voice conversation with the user.

You can SEE the user's browser through screenshots and CONTROL it through tools (click, type, navigate, scroll, etc.).

VOICE STYLE:
- Speak naturally, like a helpful friend sitting next to them
- Keep sentences SHORT (5-15 words). Voice is not text — brevity wins
- Narrate actions concisely: "Opening Calendar..." "Setting the date to March 15th..." "Done! Your event is created."
- Acknowledge the user immediately: "Got it!" "Sure thing!" "On it!"
- When waiting for a page to load, say so: "Just a moment while this loads..."
- Express warmth through intonation, not verbose language

TOOL USE:
- You have browser control tools. Use them when the user asks you to do something on the web.
- CRITICAL: After EVERY tool call, you MUST speak aloud to narrate the outcome. NEVER chain multiple tool calls silently. Always say something between actions like "Done!" or "Now setting the time..." or "Opening Calendar...".
- If you need to see what's on screen, ask for a screenshot (one will be provided automatically).
- When performing multi-step tasks, give brief voice progress updates between EACH action. The user needs to hear you working.
- Do NOT make more than 2 consecutive tool calls without speaking. The user cannot see what you're doing — they can only HEAR you.

CONVERSATION:
- You can chat about anything, not just browser tasks
- If the user asks a question, answer it conversationally
- If the user says "stop" or "wait", pause immediately
- You can ask clarifying questions before acting

IMPORTANT:
- NEVER read out URLs, HTML, or technical details unless asked
- NEVER give long lists — summarize or ask what they want to hear
- If something fails, say so simply and suggest what to try next
"""


class LiveSession:
    """Manages a Gemini Live bidirectional audio session."""

    def __init__(
        self,
        genai_client: genai.Client,
        tool_executor: ToolExecutor,
        emit_fn: Callable,
        audio_out_fn: Callable[[str], Awaitable[None]],
        transcript_fn: Callable[[str, str], Awaitable[None]],
        status_fn: Callable[[str, dict], Awaitable[None]],
        get_screenshot_fn: Callable | None = None,
        policy_engine: PolicyEngine | None = None,
        ui_graph_registry=None,
        approval_fn: Callable | None = None,
    ):
        self._client = genai_client
        self._tool_executor = tool_executor
        self._emit_fn = emit_fn
        self._audio_out_fn = audio_out_fn  # async (base64_pcm) -> None
        self._transcript_fn = transcript_fn  # async (direction, text) -> None
        self._status_fn = status_fn  # async (status, data) -> None
        self._get_screenshot_fn = get_screenshot_fn
        self._policy = policy_engine
        self._ui_graph_registry = ui_graph_registry
        self._approval_fn = approval_fn  # async () -> bool — waits for user approval
        self._connector_registry = None  # Set externally after construction
        self._session = None
        self._receive_task: asyncio.Task | None = None
        self._running = False
        self._cached_task_values: dict | None = None
        self._current_url: str = ""
        # ── In-session state tracking ──
        self._session_start: float = 0.0
        self._action_log: list[dict] = []       # {tool, args_summary, success, error?}
        self._failed_actions: list[str] = []     # concise failure descriptions
        self._completed_goals: list[str] = []    # high-level things accomplished
        self._step_count: int = 0

    async def start(self) -> None:
        """Open a Gemini Live session with audio + tool calling."""
        logger.info("Starting Gemini Live session...")
        self._session_start = time.time()
        self._action_log = []
        self._failed_actions = []
        self._completed_goals = []
        self._step_count = 0

        # Build tool declarations for Live API
        tool_declarations = [types.Tool(function_declarations=ALL_TOOLS)]

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede",
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part(text=LIVE_SYSTEM)]
            ),
            tools=tool_declarations,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

        self._session = await self._client.aio.live.connect(
            model=LIVE_MODEL,
            config=config,
        )
        self._running = True
        self._receive_task = asyncio.create_task(self._receive_loop())

        await self._status_fn("connected", {"model": LIVE_MODEL})
        logger.info("Gemini Live session started")

    async def send_audio(self, pcm_base64: str) -> None:
        """Send a chunk of user audio (PCM 16kHz) to Gemini."""
        if not self._session or not self._running:
            return
        try:
            raw_bytes = base64.b64decode(pcm_base64)
            await self._session.send_realtime_input(
                audio=types.Blob(
                    data=raw_bytes,
                    mime_type="audio/pcm;rate=16000",
                )
            )
        except Exception as e:
            logger.error(f"Failed to send audio: {e}")

    async def send_screenshot(self, screenshot_b64: str) -> None:
        """Send a screenshot to the Live session as visual context."""
        if not self._session or not self._running:
            return
        try:
            raw_bytes = base64.b64decode(screenshot_b64)
            await self._session.send_realtime_input(
                media_chunks=[types.Blob(
                    data=raw_bytes,
                    mime_type="image/jpeg",
                )]
            )
        except Exception as e:
            logger.error(f"Failed to send screenshot: {e}")

    async def send_text(self, text: str) -> None:
        """Send a text message into the live session.

        Tries deterministic execution first (calendar, gmail, youtube),
        then auto-fill if on a known app page, then falls back to Gemini.
        """
        if not self._session or not self._running:
            return

        # Try deterministic skill execution first (navigate + fill in one shot)
        det_result = await self._try_deterministic(text)
        if det_result:
            summary = f"[System: {det_result}. Tell the user it's done — narrate what happened.]"
            try:
                await self._session.send_realtime_input(text=summary)
            except Exception as e:
                logger.warning(f"Failed to send deterministic summary: {e}")
            return

        # Try auto-fill before sending to Gemini — if on a known app
        auto_result = await self._try_auto_fill(text)
        if auto_result:
            # Tell Gemini what we did so it can narrate
            summary = f"[System: Auto-filled the form with the user's values. Tell the user it's done.]"
            try:
                await self._session.send_realtime_input(text=summary)
            except Exception as e:
                logger.warning(f"Failed to send auto-fill summary to Live session: {e}")
            return

        try:
            await self._session.send_realtime_input(text=text)
        except Exception as e:
            logger.error(f"Failed to send text: {e}")

    async def _receive_loop(self) -> None:
        """Process all responses from Gemini Live — audio, transcripts, tool calls."""
        try:
            async for response in self._session.receive():
                if not self._running:
                    break

                # Audio output from model
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            audio_b64 = base64.b64encode(part.inline_data.data).decode()
                            await self._audio_out_fn(audio_b64)

                # Input transcription (what the user said)
                if response.server_content and response.server_content.input_transcription:
                    text = response.server_content.input_transcription.text
                    if text:
                        await self._transcript_fn("in", text)
                        logger.info(f"User said: {text[:80]}")

                # Output transcription (what the model said)
                if response.server_content and response.server_content.output_transcription:
                    text = response.server_content.output_transcription.text
                    if text:
                        await self._transcript_fn("out", text)
                        logger.info(f"Agent said: {text[:80]}")

                # Tool calls — Gemini wants to perform browser actions
                if response.tool_call:
                    await self._handle_tool_calls(response.tool_call.function_calls)

        except asyncio.CancelledError:
            logger.info("Live receive loop cancelled")
        except Exception as e:
            logger.error(f"Live receive loop error: {e}", exc_info=True)
            await self._status_fn("error", {"message": str(e)})
        finally:
            self._running = False
            await self._status_fn("disconnected", {})

    async def _try_deterministic(self, instruction: str) -> str | None:
        """Try to execute via deterministic connector skill (calendar, gmail, youtube).

        This handles the full flow: navigate to the app + fill form + save.
        Returns a summary string if successful, None if no matching skill.
        """
        if not self._connector_registry:
            return None

        match = self._connector_registry.find_deterministic_skill(instruction)
        if not match:
            return None

        skill, connector_name, skill_name = match
        logger.info(f"Live deterministic match: {connector_name}.{skill_name}")

        # Extract params from the instruction using LLM
        params = await self._extract_skill_params(instruction, skill)
        if not params:
            return None

        from backend.agent.core import TaskEvent
        await self._emit_fn(TaskEvent("action_planned", "live", {
            "action_type": f"skill_{connector_name}_{skill_name}",
            "element_description": f"Deterministic: {connector_name}.{skill_name}",
        }))

        try:
            result = await skill.executor(
                params=params,
                tool_executor=self._tool_executor,
                emit_fn=self._emit_fn,
                task_id="live",
                mode="extension",
            )
            if result.success:
                self._completed_goals.append(f"{connector_name}.{skill_name}")
                logger.info(f"Live deterministic success: {result.data}")

                # Send screenshot after so Gemini sees the result
                if self._get_screenshot_fn:
                    try:
                        screenshot_b64, url, title = await self._get_screenshot_fn()
                        if url:
                            self._current_url = url
                        if screenshot_b64:
                            await self.send_screenshot(screenshot_b64)
                    except Exception:
                        pass

                summary = f"Successfully executed {skill_name}"
                if result.data:
                    details = ", ".join(f"{k}={v}" for k, v in list(result.data.items())[:4] if v)
                    summary += f" ({details})"
                return summary
            else:
                logger.warning(f"Live deterministic failed: {result.error}")
                return None
        except Exception as e:
            logger.error(f"Live deterministic error: {e}")
            return None

    async def _extract_skill_params(self, instruction: str, skill) -> dict | None:
        """Use LLM to extract skill parameters from natural language instruction."""
        param_desc = "\n".join(f"- {p.name}: {p.description}" for p in skill.params)
        prompt = (
            f"Extract parameters from this instruction for the '{skill.name}' action.\n\n"
            f"Instruction: \"{instruction}\"\n\n"
            f"Parameters needed:\n{param_desc}\n\n"
            f"Today's date: {time.strftime('%A, %B %d, %Y')}\n\n"
            f"Return ONLY a JSON object with the parameter values. "
            f"For dates use MM/DD/YYYY format. For times use 12-hour format like '10:00am'. "
            f"Convert relative dates ('tomorrow') to absolute dates. "
            f"If a parameter is not mentioned, omit it.\n\n"
            f"JSON:"
        )
        try:
            response = await self._client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=256,
                    response_mime_type="application/json",
                ),
            )
            import json
            params = json.loads(response.text)
            logger.info(f"Live skill params extracted: {params}")
            return params
        except Exception as e:
            logger.warning(f"Live param extraction failed: {e}")
            return None

    async def _try_auto_fill(self, instruction: str) -> dict | None:
        """Try auto-fill using UI graph — same logic as fast_loop."""
        if not self._ui_graph_registry or not self._current_url:
            return None

        graph = self._ui_graph_registry.detect_and_get(self._current_url, "")
        if not graph:
            return None

        # Extract values from the user's instruction
        if not self._cached_task_values:
            try:
                from backend.uigraph.prompt import extract_task_values_llm
                self._cached_task_values = await extract_task_values_llm(
                    instruction, graph, self._client,
                )
                logger.info(f"Live auto-fill extracted: {self._cached_task_values}")
            except Exception as e:
                logger.warning(f"Live auto-fill extraction failed: {e}")
                return None

        if not self._cached_task_values:
            return None

        # Build fill_form fields from graph
        from backend.uigraph.model import NodeType
        fields = []
        for node_id in graph.interaction_sequence:
            node = graph.get_node(node_id)
            if not node or node_id not in self._cached_task_values:
                continue
            value = self._cached_task_values[node_id]
            if not value:
                continue

            hints = {}
            for key in ("placeholder", "aria", "text", "tag"):
                if node.selector_hints.get(key):
                    hints[key] = node.selector_hints[key]

            if node.node_type == NodeType.CHIP:
                action, press_enter, wait_after = "select_all_and_type", True, 100
            elif node.node_type == NodeType.INPUT:
                action, press_enter = "type", node_id in ("guests", "to_field")
                wait_after = 50
            else:
                action, press_enter, wait_after = "click", False, 50

            fields.append({
                "hints": hints, "value": value, "action": action,
                "press_enter": press_enter, "clear_first": True, "wait_after": wait_after,
            })

        if not fields:
            return None

        logger.info(f"Live auto-fill: {len(fields)} fields from graph {graph.app_id}")

        from backend.agent.core import TaskEvent
        await self._emit_fn(TaskEvent("action_planned", "live", {
            "action_type": "fill_form",
            "element_description": f"Auto-filling {len(fields)} fields",
        }))

        result = await self._tool_executor.execute(
            "fill_form", {"fields": fields},
            mode="extension", emit_fn=self._emit_fn, task_id="live",
        )
        return {"success": True, "result": f"Auto-filled {len(fields)} fields"}

    async def _handle_tool_calls(self, function_calls) -> None:
        """Execute browser tool calls from Gemini and send results back."""
        function_responses = []

        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}
            logger.info(f"Live tool call: {tool_name}({tool_args})")

            # ── Policy check ──
            if self._policy:
                decision = self._policy.evaluate(
                    action_type=tool_name,
                    risk_level=tool_args.get("risk_level", "low"),
                    confidence=0.8,
                    element_id=tool_args.get("element_description", ""),
                    url=self._current_url,
                )
                if decision.verdict == "require_approval":
                    logger.warning(f"Policy blocked: {decision.reason}")
                    await self._status_fn("approval_needed", {
                        "action": tool_name,
                        "reason": decision.reason,
                        "risk": decision.risk_level,
                    })
                    # If we have an approval function, wait for user
                    if self._approval_fn:
                        approved = await self._approval_fn()
                        if not approved:
                            function_responses.append(types.FunctionResponse(
                                name=tool_name, id=fc.id,
                                response={"success": False, "error": "User denied action"},
                            ))
                            continue
                    # No approval function — skip dangerous action
                    elif decision.verdict == "deny":
                        function_responses.append(types.FunctionResponse(
                            name=tool_name, id=fc.id,
                            response={"success": False, "error": f"Policy denied: {decision.reason}"},
                        ))
                        continue

            # Emit action event for the UI timeline
            from backend.agent.core import TaskEvent
            await self._emit_fn(TaskEvent("action_planned", "live", {
                "action_type": tool_name,
                **tool_args,
                "reasoning": f"Voice agent: {tool_name}",
            }))

            # Execute via the existing tool executor
            try:
                result = await self._tool_executor.execute(
                    tool_name, tool_args,
                    mode="extension",
                    emit_fn=self._emit_fn,
                    task_id="live",
                )
                result_dict = {"success": True, "result": str(result) if result else "ok"}

                # Track URL for policy + UI graph detection
                if tool_name == "navigate" and tool_args.get("url"):
                    self._current_url = tool_args["url"]

            except Exception as e:
                logger.error(f"Tool execution error: {e}")
                result_dict = {"success": False, "error": str(e)}

            # ── Track in-session state ──
            self._step_count += 1
            args_summary = ", ".join(f"{k}={v}" for k, v in list(tool_args.items())[:3])
            self._action_log.append({
                "step": self._step_count,
                "tool": tool_name,
                "args": args_summary[:120],
                "success": result_dict["success"],
            })
            if result_dict["success"]:
                self._completed_goals.append(f"{tool_name}({args_summary[:60]})")
            else:
                self._failed_actions.append(
                    f"Step {self._step_count}: {tool_name} failed — {result_dict.get('error', 'unknown')[:80]}"
                )

            # Emit result for UI
            event_type = "action_succeeded" if result_dict["success"] else "action_failed"
            await self._emit_fn(TaskEvent(event_type, "live", {
                "action_type": tool_name,
                **result_dict,
            }))

            function_responses.append(types.FunctionResponse(
                name=tool_name,
                id=fc.id,
                response=result_dict,
            ))

        # Send tool responses back to Gemini so it can continue
        if function_responses and self._session and self._running:
            try:
                await self._session.send_tool_response(
                    function_responses=function_responses
                )
            except Exception as e:
                logger.error(f"Failed to send tool responses: {e}")

            # After tool execution, send a fresh screenshot for visual grounding
            if self._get_screenshot_fn:
                try:
                    screenshot_b64, url, title = await self._get_screenshot_fn()
                    if url:
                        self._current_url = url
                    if screenshot_b64:
                        await self.send_screenshot(screenshot_b64)
                except Exception as e:
                    logger.debug(f"Screenshot after tool call failed: {e}")

            # Build a brief summary of what just happened
            actions_done = []
            for fr in function_responses:
                success = fr.response.get("success", False)
                status = "done" if success else "failed"
                actions_done.append(f"{fr.name}: {status}")
            actions_summary = ", ".join(actions_done)

            # ALWAYS nudge the model to speak after tool calls.
            # Without this, it silently chains more tool calls and never
            # produces audio output — the user hears nothing.
            nudge = (
                f"[System: You just completed: {actions_summary}. "
                f"NOW SPEAK to the user — tell them what you did and what's next. "
                f"Do NOT call another tool until you've spoken aloud.]"
            )
            try:
                await self._session.send_realtime_input(text=nudge)
            except Exception as e:
                logger.debug(f"Failed to send speak nudge: {e}")

    def _build_session_state(self) -> str:
        """Build a concise session state summary for Gemini context."""
        if not self._action_log:
            return ""

        lines = [f"[Session state — {self._step_count} actions taken, page: {self._current_url or 'unknown'}]"]

        # Recent actions (last 5)
        recent = self._action_log[-5:]
        for a in recent:
            status = "OK" if a["success"] else "FAILED"
            lines.append(f"  #{a['step']} {a['tool']}({a['args'][:50]}) → {status}")

        # Failures that need attention
        if self._failed_actions:
            lines.append(f"FAILURES ({len(self._failed_actions)}):")
            for f in self._failed_actions[-3:]:
                lines.append(f"  - {f}")

        # Keep it compact
        elapsed = int(time.time() - self._session_start)
        success_count = sum(1 for a in self._action_log if a["success"])
        lines.append(f"Progress: {success_count}/{self._step_count} succeeded, {elapsed}s elapsed")

        return "\n".join(lines)

    async def stop(self) -> None:
        """Close the live session gracefully."""
        self._running = False
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._session:
            try:
                self._session.close()
            except Exception as e:
                logger.debug(f"Live session close error: {e}")
            self._session = None

        if self._action_log:
            success = sum(1 for a in self._action_log if a["success"])
            elapsed = int(time.time() - self._session_start)
            logger.info(
                f"Live session ended: {success}/{self._step_count} actions succeeded, "
                f"{len(self._failed_actions)} failures, {elapsed}s"
            )
        logger.info("Gemini Live session stopped")

    @property
    def is_active(self) -> bool:
        return self._running and self._session is not None
