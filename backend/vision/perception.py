"""Gemini Vision perception for G-Axis.

Sends browser screenshots to Gemini and receives structured understanding
of the page — element locations, types, text content, and actionability.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass

from google import genai
from google.genai import types

VISION_MODEL = "gemini-2.5-pro-preview-06-05"

PERCEPTION_PROMPT = """You are the vision system for G-Axis, a web automation agent.

Analyze this browser screenshot and identify ALL interactive elements visible on the page.

For each element, provide:
- "id": a short unique identifier (e.g., "search_input", "login_btn")
- "type": one of "button", "link", "input", "dropdown", "checkbox", "tab", "menu_item", "icon_button", "other"
- "text": the visible text on/near the element
- "description": brief description of what this element does
- "x": center x coordinate (pixels from left)
- "y": center y coordinate (pixels from top)
- "width": approximate width in pixels
- "height": approximate height in pixels
- "interactable": true if the element can be clicked/typed into
- "is_sensitive": true if this is a password field, payment input, or contains PII

Also provide:
- "page_summary": 1-2 sentence summary of what this page is showing
- "current_state": what state the page is in (e.g., "showing search results", "login form", "settings page")

The screenshot is 1280x720 pixels.

Return ONLY valid JSON:
{
  "page_summary": "...",
  "current_state": "...",
  "elements": [...]
}"""

ACTION_PROMPT = """You are the action planner for G-Axis, a supervised web automation agent.

TASK: {task}

CURRENT PAGE STATE:
- URL: {url}
- Title: {title}
- Page: {page_summary}
- State: {current_state}

VISIBLE ELEMENTS:
{elements_text}

PREVIOUS ACTIONS THIS TASK:
{action_history}

Based on the current page state and the task, determine the NEXT SINGLE action to take.

Return ONLY valid JSON:
{{
  "reasoning": "Brief explanation of why this action advances the task",
  "action": {{
    "type": "click" | "type" | "scroll" | "navigate" | "press_key" | "select_all_and_type" | "wait" | "done",
    "element_id": "id of the target element (if applicable)",
    "x": center_x_coordinate,
    "y": center_y_coordinate,
    "text": "text to type (for type/select_all_and_type actions)",
    "url": "url to navigate to (for navigate action)",
    "direction": "up" | "down" (for scroll),
    "key": "Enter" | "Tab" | "Escape" (for press_key),
    "pixels": 300 (for scroll)
  }},
  "risk_level": "none" | "low" | "medium" | "high" | "critical",
  "confidence": 0.0 to 1.0,
  "is_task_complete": false,
  "completion_summary": "only if is_task_complete is true — what was accomplished"
}}

RULES:
- Return ONE action at a time. You will be called again after execution.
- If the task is complete, set action.type to "done" and is_task_complete to true.
- Mark password/payment fields as "high" or "critical" risk.
- If you cannot determine what to do, set confidence below 0.3.
- Use "select_all_and_type" when you need to clear an input field first.
- NEVER guess URLs. Only navigate to URLs visible on the page or well-known domains."""


@dataclass
class PerceivedElement:
    id: str
    type: str
    text: str
    description: str
    x: int
    y: int
    width: int
    height: int
    interactable: bool
    is_sensitive: bool


@dataclass
class PagePerception:
    page_summary: str
    current_state: str
    elements: list[PerceivedElement]
    url: str
    title: str
    timestamp: float


@dataclass
class PlannedAction:
    reasoning: str
    action_type: str
    element_id: str | None
    x: int | None
    y: int | None
    text: str | None
    url: str | None
    direction: str | None
    key: str | None
    pixels: int
    risk_level: str
    confidence: float
    is_task_complete: bool
    completion_summary: str | None


class VisionPerception:
    """Uses Gemini vision to understand browser screenshots."""

    def __init__(self, api_key: str | None = None):
        self.client = genai.Client(api_key=api_key)

    async def perceive(self, screenshot_b64: str, url: str, title: str) -> PagePerception:
        """Analyze a screenshot and return structured page understanding."""
        image_bytes = base64.b64decode(screenshot_b64)

        response = await self.client.aio.models.generate_content(
            model=VISION_MODEL,
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        types.Part.from_text(text=PERCEPTION_PROMPT),
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=4096,
                response_mime_type="application/json",
            ),
        )

        parsed = _parse_json(response.text or "{}")

        elements = [
            PerceivedElement(
                id=el.get("id", f"el_{i}"),
                type=el.get("type", "other"),
                text=el.get("text", ""),
                description=el.get("description", ""),
                x=el.get("x", 0),
                y=el.get("y", 0),
                width=el.get("width", 0),
                height=el.get("height", 0),
                interactable=el.get("interactable", False),
                is_sensitive=el.get("is_sensitive", False),
            )
            for i, el in enumerate(parsed.get("elements", []))
        ]

        return PagePerception(
            page_summary=parsed.get("page_summary", ""),
            current_state=parsed.get("current_state", ""),
            elements=elements,
            url=url,
            title=title,
            timestamp=time.time(),
        )

    async def plan_action(
        self,
        task: str,
        perception: PagePerception,
        action_history: list[dict],
        screenshot_b64: str,
    ) -> PlannedAction:
        """Given the current page state and task, plan the next action."""
        elements_text = "\n".join(
            f"- [{el.id}] {el.type}: \"{el.text}\" at ({el.x},{el.y}) "
            f"{'SENSITIVE' if el.is_sensitive else ''}"
            for el in perception.elements
            if el.interactable
        )

        history_text = "\n".join(
            f"  {i+1}. {a.get('action_type', '?')} — {a.get('reasoning', '?')}"
            for i, a in enumerate(action_history[-10:])  # last 10 actions
        ) or "  (none yet)"

        prompt = ACTION_PROMPT.format(
            task=task,
            url=perception.url,
            title=perception.title,
            page_summary=perception.page_summary,
            current_state=perception.current_state,
            elements_text=elements_text or "(no interactive elements found)",
            action_history=history_text,
        )

        image_bytes = base64.b64decode(screenshot_b64)

        response = await self.client.aio.models.generate_content(
            model=VISION_MODEL,
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        types.Part.from_text(text=prompt),
                    ]
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )

        parsed = _parse_json(response.text or "{}")
        action = parsed.get("action", {})

        return PlannedAction(
            reasoning=parsed.get("reasoning", ""),
            action_type=action.get("type", "wait"),
            element_id=action.get("element_id"),
            x=action.get("x"),
            y=action.get("y"),
            text=action.get("text"),
            url=action.get("url"),
            direction=action.get("direction"),
            key=action.get("key"),
            pixels=action.get("pixels", 300),
            risk_level=parsed.get("risk_level", "medium"),
            confidence=parsed.get("confidence", 0.5),
            is_task_complete=parsed.get("is_task_complete", False),
            completion_summary=parsed.get("completion_summary"),
        )


def _parse_json(text: str) -> dict:
    """Parse JSON from model output, handling markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Failed to parse JSON from model output: {cleaned[:200]}")
