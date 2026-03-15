"""Base connector and skill definitions.

A Connector groups related Skills. Each Skill defines:
  - What it does (name, description)
  - What parameters it needs
  - How to execute:
      DETERMINISTIC — direct browser actions, no LLM (fastest, most reliable)
      BROWSER       — LLM follows template instructions (flexible, slower)
      API           — direct API call (needs auth)
      HYBRID        — try API first, fall back to browser
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger("gaxis.connectors")


# Type alias for deterministic skill executors.
# Signature: (params, tool_executor, emit_fn, task_id, mode) → SkillResult
SkillExecutorFn = Callable[
    [dict, Any, Any, str, str],
    Awaitable["SkillResult"],
]


class SkillMode(str, Enum):
    """How a skill is executed."""
    DETERMINISTIC = "deterministic"  # Direct browser actions, no LLM
    API = "api"                      # Direct API call (fast, needs auth)
    BROWSER = "browser"              # LLM follows browser template
    HYBRID = "hybrid"                # Try API first, fall back to browser


@dataclass
class SkillParam:
    """A parameter for a skill."""
    name: str
    description: str
    type: str = "string"          # string, integer, boolean, array, object
    required: bool = True
    enum: list[str] | None = None
    default: Any = None


@dataclass
class SkillResult:
    """Result of executing a skill."""
    success: bool
    data: dict = field(default_factory=dict)
    error: str | None = None
    # If browser mode, this is the instruction for the agent to execute
    browser_instruction: str | None = None


@dataclass
class Skill:
    """A single capability exposed by a connector.

    Skills with an `executor` function run deterministically — they call
    ToolExecutor directly with predetermined browser actions (navigate,
    fill_form, click-by-hint).  No LLM in the loop.  100x faster, zero
    hallucination, fully reliable.
    """
    name: str                          # e.g. "send_email"
    description: str                   # Human-readable description
    connector: str                     # Parent connector name
    params: list[SkillParam] = field(default_factory=list)
    mode: SkillMode = SkillMode.BROWSER
    # For browser mode: template instruction with {param} placeholders
    browser_template: str = ""
    # URL to navigate to for browser-based execution
    start_url: str = ""
    # Tags for discovery
    tags: list[str] = field(default_factory=list)
    # Examples for the LLM
    examples: list[str] = field(default_factory=list)
    # Deterministic executor — if set, skill runs without LLM
    executor: SkillExecutorFn | None = None

    @property
    def has_executor(self) -> bool:
        """True if this skill can run deterministically (no LLM)."""
        return self.executor is not None

    def to_gemini_tool(self):
        """Convert to Gemini FunctionDeclaration for tool calling."""
        from google.genai import types

        properties = {}
        required = []
        for p in self.params:
            prop: dict[str, Any] = {
                "type": p.type,
                "description": p.description,
            }
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return types.FunctionDeclaration(
            name=f"skill_{self.connector}_{self.name}",
            description=f"[{self.connector}] {self.description}",
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )

    def render_browser_instruction(self, params: dict) -> str:
        """Fill the browser template with actual parameter values."""
        instruction = self.browser_template
        for key, value in params.items():
            instruction = instruction.replace(f"{{{key}}}", str(value))
        return instruction

    @property
    def full_name(self) -> str:
        return f"{self.connector}.{self.name}"


class BaseConnector(ABC):
    """Abstract base for all connectors."""

    name: str = ""
    description: str = ""
    icon: str = ""           # Emoji or icon identifier
    category: str = ""       # e.g. "productivity", "communication"

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._authenticated: bool = False
        self._setup()

    @abstractmethod
    def _setup(self) -> None:
        """Register skills in subclass."""
        ...

    def register_skill(self, skill: Skill) -> None:
        """Register a skill with this connector."""
        skill.connector = self.name
        self._skills[skill.name] = skill
        logger.debug(f"[{self.name}] Registered skill: {skill.name}")

    @property
    def skills(self) -> dict[str, Skill]:
        return self._skills

    def get_skill(self, name: str) -> Skill | None:
        return self._skills.get(name)

    async def execute_skill(
        self,
        skill_name: str,
        params: dict,
        tool_executor: Any = None,
        emit_fn: Any = None,
        task_id: str = "",
        mode: str = "extension",
    ) -> SkillResult:
        """Execute a skill.

        Execution priority:
          1. DETERMINISTIC — skill.executor runs browser actions directly
          2. BROWSER — returns rendered template for LLM to follow
          3. API — subclass overrides for direct API calls
        """
        skill = self._skills.get(skill_name)
        if not skill:
            return SkillResult(success=False, error=f"Unknown skill: {skill_name}")

        # Fill in defaults for optional params
        for p in skill.params:
            if not p.required and p.name not in params and p.default is not None:
                params[p.name] = p.default

        # Deterministic execution — no LLM, direct browser actions
        if skill.has_executor and tool_executor is not None:
            logger.info(f"[{self.name}] Deterministic exec: {skill_name}")
            try:
                return await skill.executor(
                    params, tool_executor, emit_fn, task_id, mode,
                )
            except Exception as e:
                logger.error(f"[{self.name}] Executor failed: {e}", exc_info=True)
                return SkillResult(success=False, error=str(e))

        if skill.mode in (SkillMode.BROWSER, SkillMode.DETERMINISTIC):
            # Fallback: return browser instruction for LLM
            instruction = skill.render_browser_instruction(params)
            return SkillResult(
                success=True,
                browser_instruction=instruction,
                data={"start_url": skill.start_url, "params": params},
            )

        # API mode — subclass should override
        return SkillResult(
            success=False,
            error=f"API execution not implemented for {skill.full_name}",
        )

    def get_skills_prompt(self) -> str:
        """Generate a prompt section describing this connector's skills."""
        lines = [f"### {self.name} ({self.description})"]
        for skill in self._skills.values():
            param_desc = ", ".join(
                f"{p.name}: {p.description}" for p in skill.params
            )
            lines.append(f"  - {skill.full_name}: {skill.description}")
            if param_desc:
                lines.append(f"    Parameters: {param_desc}")
            if skill.examples:
                lines.append(f"    Examples: {'; '.join(skill.examples[:2])}")
        return "\n".join(lines)
