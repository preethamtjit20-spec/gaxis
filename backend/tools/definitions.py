"""Gemini function/tool declarations for browser control.

These are passed to Gemini so it can call browser actions natively
via function calling instead of generating JSON text.
"""

from google.genai import types

# ─── BROWSER ACTION TOOLS ─────────────────────────────────────

click_tool = types.FunctionDeclaration(
    name="click",
    description="Click on an element at the given screen coordinates. Use this for buttons, links, checkboxes, radio buttons, tabs, and any clickable element.",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate (pixels from left edge)"},
            "y": {"type": "integer", "description": "Y coordinate (pixels from top edge)"},
            "element_description": {"type": "string", "description": "What element you're clicking and why"},
        },
        "required": ["x", "y", "element_description"],
    },
)

type_text_tool = types.FunctionDeclaration(
    name="type_text",
    description="Click on an input field and type text into it. If clear_first is true, selects all existing text before typing (useful for replacing text in a field).",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate of the input field"},
            "y": {"type": "integer", "description": "Y coordinate of the input field"},
            "text": {"type": "string", "description": "The text to type"},
            "clear_first": {"type": "boolean", "description": "If true, clear the field before typing (select all + replace)"},
        },
        "required": ["x", "y", "text"],
    },
)

navigate_tool = types.FunctionDeclaration(
    name="navigate",
    description="Navigate the browser to a specific URL. Only use well-known URLs or URLs visible on the current page.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to navigate to"},
        },
        "required": ["url"],
    },
)

scroll_tool = types.FunctionDeclaration(
    name="scroll",
    description="Scroll the page up or down to reveal more content.",
    parameters={
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["up", "down"], "description": "Scroll direction"},
            "pixels": {"type": "integer", "description": "How many pixels to scroll (default 400)"},
        },
        "required": ["direction"],
    },
)

press_key_tool = types.FunctionDeclaration(
    name="press_key",
    description="Press a keyboard key. Common keys: Enter, Tab, Escape, Backspace, ArrowDown, ArrowUp.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "The key to press (e.g., 'Enter', 'Tab', 'Escape')"},
        },
        "required": ["key"],
    },
)

hover_tool = types.FunctionDeclaration(
    name="hover",
    description="Move the mouse to hover over an element. Useful for revealing dropdown menus or tooltips.",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate to hover"},
            "y": {"type": "integer", "description": "Y coordinate to hover"},
        },
        "required": ["x", "y"],
    },
)

wait_tool = types.FunctionDeclaration(
    name="wait",
    description="Wait for the page to load or for an animation to complete. Use when the page is still loading.",
    parameters={
        "type": "object",
        "properties": {
            "seconds": {"type": "number", "description": "How many seconds to wait (1-5)"},
            "reason": {"type": "string", "description": "Why waiting is needed"},
        },
        "required": ["reason"],
    },
)

# ─── DATA TOOLS ────────────────────────────────────────────────

extract_data_tool = types.FunctionDeclaration(
    name="extract_data",
    description="Extract structured data from the current page. Describe what data to extract and in what format.",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "What data to extract from the page"},
            "data": {"type": "object", "description": "The extracted data as a JSON object"},
        },
        "required": ["description", "data"],
    },
)

# ─── CONTROL FLOW TOOLS ───────────────────────────────────────

task_complete_tool = types.FunctionDeclaration(
    name="task_complete",
    description="Signal that the current task or subtask is complete. Provide a summary of what was accomplished.",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "What was accomplished"},
            "data": {"type": "object", "description": "Any structured data to return"},
        },
        "required": ["summary"],
    },
)

task_failed_tool = types.FunctionDeclaration(
    name="task_failed",
    description="Signal that the task cannot be completed. Explain why.",
    parameters={
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why the task failed"},
        },
        "required": ["reason"],
    },
)

delegate_tool = types.FunctionDeclaration(
    name="delegate",
    description="Delegate work to a specialist agent. Use this to assign subtasks.",
    parameters={
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "enum": ["navigator", "form_filler", "data_extractor", "verifier"],
                "description": "Which specialist agent to delegate to",
            },
            "instruction": {"type": "string", "description": "What the specialist should do"},
        },
        "required": ["agent", "instruction"],
    },
)

# ─── TOOL SETS PER AGENT ──────────────────────────────────────

ORCHESTRATOR_TOOLS = [delegate_tool, task_complete_tool, task_failed_tool]

NAVIGATOR_TOOLS = [
    click_tool, navigate_tool, scroll_tool, press_key_tool,
    hover_tool, wait_tool, task_complete_tool, task_failed_tool,
]

FORM_FILLER_TOOLS = [
    click_tool, type_text_tool, press_key_tool, scroll_tool,
    wait_tool, task_complete_tool, task_failed_tool,
]

DATA_EXTRACTOR_TOOLS = [
    scroll_tool, click_tool, extract_data_tool, wait_tool,
    task_complete_tool, task_failed_tool,
]

VERIFIER_TOOLS = [
    scroll_tool, click_tool, extract_data_tool,
    task_complete_tool, task_failed_tool,
]

ALL_TOOLS = [
    click_tool, type_text_tool, navigate_tool, scroll_tool,
    press_key_tool, hover_tool, wait_tool, extract_data_tool,
    task_complete_tool, task_failed_tool,
]
