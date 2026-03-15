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
    description="Click on an input field and type text into it. Set press_enter=true to submit the text (e.g., after typing a search query). Set clear_first=true to replace existing text.",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate of the input field"},
            "y": {"type": "integer", "description": "Y coordinate of the input field"},
            "text": {"type": "string", "description": "The text to type"},
            "press_enter": {"type": "boolean", "description": "Whether to press Enter after typing. Set true for search boxes, URL bars, and any field that needs submission."},
            "clear_first": {"type": "boolean", "description": "If true, clear the field before typing (select all + replace)"},
        },
        "required": ["x", "y", "text", "press_enter"],
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

# ─── ROLLBACK TOOL ─────────────────────────────────────────────

rollback_tool = types.FunctionDeclaration(
    name="rollback",
    description=(
        "Undo the last N browser actions. Use when you typed in the wrong field, "
        "navigated to the wrong page, or filled incorrect values. "
        "The system will reverse your recent actions (clear fields, navigate back, etc.) "
        "so you can retry correctly. Only call this when you KNOW a previous action was wrong."
    ),
    parameters={
        "type": "object",
        "properties": {
            "steps": {
                "type": "integer",
                "description": "How many actions to undo (1-5). Default 1.",
            },
            "reason": {
                "type": "string",
                "description": "Why you need to rollback (e.g., 'typed title into date field')",
            },
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

task_partial_tool = types.FunctionDeclaration(
    name="task_partial",
    description=(
        "Signal that the task is PARTIALLY complete — some parts succeeded but "
        "specific items are missing or incorrect. Use this instead of task_failed "
        "when the core action was done but details need fixing. "
        "Example: calendar event created but guest not added, or email sent but CC missing."
    ),
    parameters={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "What was successfully completed",
            },
            "missing": {
                "type": "array",
                "description": "List of specific items that are missing or incorrect",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "description": "What's missing (e.g. 'guest', 'location', 'end_time')",
                        },
                        "expected": {
                            "type": "string",
                            "description": "What the value should be",
                        },
                        "actual": {
                            "type": "string",
                            "description": "What is currently shown (empty string if missing entirely)",
                        },
                        "fix_instruction": {
                            "type": "string",
                            "description": "How to fix it (e.g. 'Click Add guests, type john@example.com, press Enter')",
                        },
                    },
                    "required": ["field", "expected", "fix_instruction"],
                },
            },
        },
        "required": ["summary", "missing"],
    },
)

confirm_action_tool = types.FunctionDeclaration(
    name="confirm_action",
    description=(
        "Show a preview card to the user and wait for their confirmation before proceeding. "
        "Use this for significant actions like creating calendar events, sending emails, "
        "making purchases, or any action the user should review first. "
        "The card shows structured details (title, date, time, etc.) with Create/Cancel buttons."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action_type": {
                "type": "string",
                "enum": ["calendar", "email", "sheet", "doc", "default"],
                "description": "Type of action (determines the icon)",
            },
            "card_title": {"type": "string", "description": "Card header, e.g. 'New Calendar Event'"},
            "button_label": {"type": "string", "description": "Confirm button text, e.g. 'Create' or 'Send'"},
            "fields": {
                "type": "array",
                "description": "List of fields to display in the card",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Field type: title, date, time, duration, location, person, link, to, subject, description"},
                        "value": {"type": "string", "description": "Field value to display"},
                        "label": {"type": "string", "description": "Optional label below the value"},
                        "primary": {"type": "boolean", "description": "If true, shows as a large highlighted field (use for the main item name)"},
                    },
                    "required": ["key", "value"],
                },
            },
        },
        "required": ["action_type", "card_title", "fields"],
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

fill_form_tool = types.FunctionDeclaration(
    name="fill_form",
    description=(
        "BATCH fill multiple form fields in one action. MUCH faster than filling one field at a time. "
        "Use this when a UI GRAPH provides FILL values and you know all the fields to fill. "
        "Each field needs: hints (placeholder/aria/text for DOM query), value, action type. "
        "The content script finds elements by text matching (not coordinates) and fills them sequentially."
    ),
    parameters={
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "description": "List of form fields to fill",
                "items": {
                    "type": "object",
                    "properties": {
                        "hints": {
                            "type": "object",
                            "description": "DOM query hints: { placeholder, aria, text, tag }",
                            "properties": {
                                "placeholder": {"type": "string"},
                                "aria": {"type": "string"},
                                "text": {"type": "string"},
                                "tag": {"type": "string"},
                            },
                        },
                        "value": {"type": "string", "description": "Text to type into the field"},
                        "action": {
                            "type": "string",
                            "enum": ["type", "click", "select_all_and_type"],
                            "description": "Action type (default: type)",
                        },
                        "press_enter": {"type": "boolean", "description": "Press Enter after typing (for adding guests, confirming chips)"},
                        "clear_first": {"type": "boolean", "description": "Clear field before typing (default true)"},
                        "wait_after": {"type": "integer", "description": "Ms to wait after this field (default 30 in fast mode)"},
                    },
                    "required": ["hints"],
                },
            },
        },
        "required": ["fields"],
    },
)

plan_task_tool = types.FunctionDeclaration(
    name="plan_task",
    description="Decompose a task into ordered subtasks. Each subtask has a specialist agent and instruction.",
    parameters={
        "type": "object",
        "properties": {
            "subtasks": {
                "type": "array",
                "description": "Ordered list of subtasks to execute",
                "items": {
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "enum": ["navigator", "form_filler", "data_extractor", "verifier"],
                            "description": "Which specialist agent handles this subtask",
                        },
                        "instruction": {"type": "string", "description": "What this subtask should accomplish"},
                    },
                    "required": ["agent", "instruction"],
                },
            },
            "strategy": {"type": "string", "description": "Brief description of the overall strategy"},
        },
        "required": ["subtasks"],
    },
)

# ─── TOOL SETS PER AGENT ──────────────────────────────────────

PLANNER_TOOLS = [plan_task_tool, task_failed_tool]

ORCHESTRATOR_TOOLS = [delegate_tool, confirm_action_tool, task_failed_tool]

NAVIGATOR_TOOLS = [
    click_tool, type_text_tool, navigate_tool, scroll_tool, press_key_tool,
    hover_tool, wait_tool, rollback_tool, confirm_action_tool, task_complete_tool, task_failed_tool,
]

FORM_FILLER_TOOLS = [
    click_tool, type_text_tool, press_key_tool, scroll_tool,
    wait_tool, rollback_tool, task_complete_tool, task_failed_tool,
]

DATA_EXTRACTOR_TOOLS = [
    scroll_tool, click_tool, extract_data_tool, wait_tool,
    task_complete_tool, task_failed_tool,
]

VERIFIER_TOOLS = [
    scroll_tool, click_tool, extract_data_tool,
    task_complete_tool, task_partial_tool, task_failed_tool,
]

ALL_TOOLS = [
    click_tool, type_text_tool, navigate_tool, scroll_tool,
    press_key_tool, hover_tool, wait_tool, extract_data_tool,
    fill_form_tool, rollback_tool, task_complete_tool, task_failed_tool,
]
